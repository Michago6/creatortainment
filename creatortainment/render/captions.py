"""Pure word-chunk captioning and active-word resolution."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont


@dataclass(frozen=True)
class CaptionChunk:
    """A caption chunk and the scene-local word indexes it contains."""

    words: tuple[str, ...]
    word_indices: tuple[int, ...]


@dataclass(frozen=True)
class RenderedCaption:
    """A rendered caption image and its position within the video canvas."""

    image: Image.Image
    position: tuple[int, int]


class CaptionImageCache:
    """Cache caption images while retaining render and hit counts for diagnostics."""

    def __init__(
        self,
        style: dict[str, Any],
        resolution: tuple[int, int],
    ) -> None:
        self.style = style
        self.resolution = resolution
        self._images: dict[tuple[tuple[str, ...], int], RenderedCaption] = {}
        self.render_count = 0
        self.hit_count = 0

    def get(self, chunk: CaptionChunk, active_word_index: int) -> RenderedCaption:
        key = (chunk.words, active_word_index)
        cached = self._images.get(key)
        if cached is not None:
            self.hit_count += 1
            return cached
        rendered = render_caption_chunk(
            chunk,
            active_word_index,
            self.style,
            self.resolution,
        )
        self._images[key] = rendered
        self.render_count += 1
        return rendered


def _caption_font_path(style: dict[str, Any]) -> str | None:
    requested = style.get("font")
    if isinstance(requested, str) and Path(requested).is_file():
        return requested
    for candidate in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf",
    ):
        if Path(candidate).is_file():
            return candidate
    return None


def _load_caption_font(style: dict[str, Any]) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    size = int(style.get("font_size", 48))
    path = _caption_font_path(style)
    return ImageFont.truetype(path, size) if path else ImageFont.load_default(size)


def caption_position(
    image_size: tuple[int, int],
    resolution: tuple[int, int],
    style: dict[str, Any],
) -> tuple[int, int]:
    """Return placement using the caption block's bottom edge as vertical anchor."""
    image_width, image_height = image_size
    canvas_width, canvas_height = resolution
    bottom_margin = max(24, round(canvas_height * 0.04))
    position = style.get("position", "bottom_center")
    vertical_fraction = style.get("vertical_position_frac")
    if vertical_fraction is not None:
        if (
            isinstance(vertical_fraction, bool)
            or not isinstance(vertical_fraction, (int, float))
            or not 0.0 <= vertical_fraction <= 1.0
        ):
            raise ValueError("vertical_position_frac must be a number between 0 and 1.")
        anchor_y = round(float(vertical_fraction) * canvas_height)
    else:
        anchor_y = canvas_height - bottom_margin
    if position == "bottom_center":
        return ((canvas_width - image_width) // 2, anchor_y - image_height)
    if position == "center":
        if vertical_fraction is None:
            anchor_y = canvas_height // 2 + image_height // 2
        return ((canvas_width - image_width) // 2, anchor_y - image_height)
    raise ValueError(f"Unsupported caption position: {position!r}")


def render_caption_chunk(
    chunk: CaptionChunk,
    active_word_index: int,
    style: dict[str, Any],
    resolution: tuple[int, int],
) -> RenderedCaption:
    """Render one caption chunk, highlighting only the active word by color."""
    if active_word_index not in chunk.word_indices:
        raise ValueError("active_word_index must belong to the caption chunk.")

    font = _load_caption_font(style)
    stroke_width = int(style.get("stroke_width", 0))
    stroke_fill = style.get("stroke_color", "#000000")
    normal_fill = style.get("color", "#FFFFFF")
    highlight_fill = style.get("highlight_color", normal_fill)
    horizontal_margin = max(24, round(resolution[0] * 0.06))
    padding_x = horizontal_margin // 2
    padding_y = max(12, int(style.get("font_size", 48)) // 4)
    draw_probe = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    word_sizes = [
        draw_probe.textbbox(
            (0, 0),
            word,
            font=font,
            stroke_width=stroke_width,
        )
        for word in chunk.words
    ]
    space_width = draw_probe.textlength(" ", font=font)
    content_width = sum(
        bbox[2] - bbox[0] for bbox in word_sizes
    ) + round(space_width) * max(0, len(chunk.words) - 1)
    content_height = max(bbox[3] - bbox[1] for bbox in word_sizes)
    image = Image.new(
        "RGBA",
        (content_width + 2 * padding_x, content_height + 2 * padding_y),
        "#000000",
    )
    draw = ImageDraw.Draw(image)
    x = padding_x
    baseline_y = padding_y - min(bbox[1] for bbox in word_sizes)
    for word, bbox, local_index in zip(
        chunk.words, word_sizes, chunk.word_indices
    ):
        draw.text(
            (x, baseline_y),
            word,
            font=font,
            fill=highlight_fill if local_index == active_word_index else normal_fill,
            stroke_width=stroke_width,
            stroke_fill=stroke_fill,
        )
        x += round(draw.textlength(word, font=font)) + round(space_width)
    return RenderedCaption(
        image=image,
        position=caption_position(image.size, resolution, style),
    )


def wrap_caption_lines(
    narration_text: str,
    words_per_chunk: int = 3,
    max_chars_per_line: int | None = None,
) -> list[CaptionChunk]:
    """Group words by chunk size, splitting early when the character cap is exceeded."""
    if words_per_chunk <= 0:
        raise ValueError("words_per_chunk must be greater than zero.")
    if max_chars_per_line is not None and max_chars_per_line <= 0:
        raise ValueError("max_chars_per_line must be greater than zero.")

    words = narration_text.split()
    chunks: list[CaptionChunk] = []
    current_words: list[str] = []
    current_indices: list[int] = []
    for index, word in enumerate(words):
        candidate = " ".join((*current_words, word))
        if current_words and (
            len(current_words) >= words_per_chunk
            or (
                max_chars_per_line is not None
                and len(candidate) > max_chars_per_line
            )
        ):
            chunks.append(CaptionChunk(tuple(current_words), tuple(current_indices)))
            current_words = []
            current_indices = []
        current_words.append(word)
        current_indices.append(index)
    if current_words:
        chunks.append(CaptionChunk(tuple(current_words), tuple(current_indices)))
    return chunks


def resolve_active_caption(
    scene: dict[str, Any],
    absolute_time_sec: float,
    wrapped_lines: list[CaptionChunk],
    word_timestamps: list[dict[str, Any]],
    *,
    word_offset: int = 0,
) -> tuple[int, int] | None:
    """Return current chunk index and local word index, or None before speech starts."""
    if not wrapped_lines:
        return None
    all_indices = [index for chunk in wrapped_lines for index in chunk.word_indices]
    if not all_indices:
        return None
    starts = [
        float(word_timestamps[word_offset + index]["start"])
        for index in all_indices
    ]
    if absolute_time_sec < starts[0]:
        return None
    active_position = 0
    for position, start in enumerate(starts):
        if absolute_time_sec >= start:
            active_position = position
        else:
            break
    active_local_index = all_indices[active_position]
    for chunk_index, chunk in enumerate(wrapped_lines):
        if active_local_index in chunk.word_indices:
            return chunk_index, active_local_index
    raise ValueError(f"Word index {active_local_index} is not present in caption chunks.")
