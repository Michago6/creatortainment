"""Dependency-light storyboard renderer for the first pipeline milestone."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont


def storyboard_panel_size(
    resolution: tuple[int, int], panel_width: int = 360
) -> tuple[int, int]:
    """Return a preview panel that preserves the canonical canvas aspect ratio."""
    width, height = resolution
    return panel_width, max(1, math.ceil(panel_width * height / width))


def storyboard_columns(resolution: tuple[int, int], scene_count: int) -> int:
    """Choose a readable grid, giving landscape scenes larger preview panels."""
    if scene_count <= 0:
        return 1
    if resolution[0] > resolution[1] and scene_count >= 4:
        return min(2, scene_count)
    return min(4, scene_count)


def storyboard_sheet_size(
    resolution: tuple[int, int], scene_count: int, panel_width: int = 360
) -> tuple[int, int]:
    """Return the contact-sheet dimensions for the scene count and canvas ratio."""
    columns = storyboard_columns(resolution, scene_count)
    sheet_width = 1440 if resolution[0] > resolution[1] else 1080
    panel_width = max(1, sheet_width // columns)
    panel_width, panel_height = storyboard_panel_size(resolution, panel_width)
    rows = (scene_count + columns - 1) // columns
    return columns * panel_width, rows * panel_height


class AssetDimensionCache:
    def __init__(self) -> None:
        self._dimensions: dict[Path, tuple[int, int]] = {}

    def dimensions(self, path: Path) -> tuple[int, int]:
        if path not in self._dimensions:
            with Image.open(path) as image:
                self._dimensions[path] = image.size
        return self._dimensions[path]


def _storyboard_keyframe(element: dict[str, Any]) -> dict[str, Any]:
    """Use the final visible state, or the final authored state as fallback."""
    keyframes = element["keyframes"]
    for keyframe in reversed(keyframes):
        if float(keyframe.get("opacity", 1.0)) > 0.0:
            return keyframe
    return keyframes[-1]


def _asset_path(registry: dict[str, Any], key: str, assets_root: Path) -> Path:
    relative_path = Path(registry[key])
    if relative_path.parts and relative_path.parts[0] == "assets":
        relative_path = Path(*relative_path.parts[1:])
    return assets_root / relative_path


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for candidate in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
    ):
        if Path(candidate).is_file():
            return ImageFont.truetype(candidate, size)
    return ImageFont.load_default()


def wrap_caption(
    text: str,
    draw: ImageDraw.ImageDraw,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    max_width: int,
) -> list[str]:
    """Wrap caption words to the available pixel width, not a fixed character count."""
    lines: list[str] = []
    line = ""
    for word in text.split():
        candidate = f"{line} {word}".strip()
        if line and draw.textlength(candidate, font=font) > max_width:
            lines.append(line)
            line = word
        else:
            line = candidate
    if line:
        lines.append(line)
    return lines


def caption_box_height(
    line_count: int,
    line_height: int,
    padding: int,
    max_height: int,
) -> int:
    """Size the caption box from its text block plus top and bottom padding."""
    return min(max_height, padding * 2 + line_height * line_count)


def _place_element(
    panel: Image.Image,
    element: dict[str, Any],
    registry: dict[str, Any],
    assets_root: Path,
    canvas_size: tuple[int, int],
    dimension_cache: AssetDimensionCache,
) -> None:
    asset_path = _asset_path(registry, element["asset"], assets_root)
    if not asset_path.is_file():
        return

    keyframe = _storyboard_keyframe(element)
    image = Image.open(asset_path).convert("RGBA")
    native_width, native_height = dimension_cache.dimensions(asset_path)
    target_height = keyframe.get("target_height_frac")
    target_width = keyframe.get("target_width_frac")
    if target_height is not None and target_width is not None and keyframe.get("stretch") is True:
        target_size = (
            max(1, round(target_width * canvas_size[0])),
            max(1, round(target_height * canvas_size[1])),
        )
    elif target_height is not None:
        scale = (float(target_height) * canvas_size[1]) / native_height
        target_size = (max(1, round(native_width * scale)), max(1, round(native_height * scale)))
    else:
        scale = (float(target_width) * canvas_size[0]) / native_width
        target_size = (max(1, round(native_width * scale)), max(1, round(native_height * scale)))
    image = image.resize(target_size, Image.Resampling.LANCZOS)
    opacity = max(0.0, min(1.0, float(keyframe.get("opacity", 1.0))))
    if opacity < 1.0:
        alpha = image.getchannel("A").point(lambda value: round(value * opacity))
        image.putalpha(alpha)

    source_width, source_height = canvas_size
    panel_x, panel_y = panel.size
    scene_x, scene_y = keyframe["pos"]
    center_x = round(float(scene_x) * panel_x / source_width)
    center_y = round(float(scene_y) * panel_y / source_height)
    anchor = element["anchor"]
    if anchor == "top_left":
        destination = (center_x, center_y)
    elif anchor == "bottom_center":
        destination = (center_x - image.width // 2, center_y - image.height)
    else:
        destination = (center_x - image.width // 2, center_y - image.height // 2)
    panel.alpha_composite(image, destination)


def render_storyboard(script: dict[str, Any], assets_root: Path, output_path: Path) -> None:
    scenes = script["scenes"]
    canvas_size = tuple(script["project"]["resolution"])
    columns = storyboard_columns(canvas_size, len(scenes))
    sheet_width = 1440 if canvas_size[0] > canvas_size[1] else 1080
    panel_width, panel_height = storyboard_panel_size(
        canvas_size,
        max(1, sheet_width // columns),
    )
    rows = (len(scenes) + columns - 1) // columns
    sheet = Image.new("RGB", (columns * panel_width, rows * panel_height), "#20242b")
    canvas_width, canvas_height = canvas_size
    title_font = _font(max(18, round(canvas_width * 24 / panel_width)))
    body_font = _font(max(12, round(canvas_width * 16 / panel_width)))
    dimension_cache = AssetDimensionCache()

    for index, scene in enumerate(scenes):
        x = (index % columns) * panel_width
        y = (index // columns) * panel_height
        panel = Image.new("RGBA", (canvas_width, canvas_height), "#26384d")
        draw = ImageDraw.Draw(panel)
        asset_path = _asset_path(script["asset_registry"], scene["bg"], assets_root)
        if asset_path.is_file():
            background = Image.open(asset_path).convert("RGB")
            scale = max(canvas_width / background.width, canvas_height / background.height)
            background = background.resize(
                (round(background.width * scale), round(background.height * scale)),
                Image.Resampling.LANCZOS,
            )
            left = (background.width - canvas_width) // 2
            top = (background.height - canvas_height) // 2
            panel.paste(
                background.crop((left, top, left + canvas_width, top + canvas_height)),
                (0, 0),
            )

        elements = sorted(scene.get("elements", []), key=lambda item: item.get("z_index", 0))
        for element in elements:
            _place_element(
                panel,
                element,
                script["asset_registry"],
                assets_root,
                canvas_size,
                dimension_cache,
            )

        header_height = round(canvas_height * 52 / panel_height)
        draw.rectangle((0, 0, canvas_width, header_height), fill="#111827")
        draw.text(
            (round(canvas_width * 16 / panel_width), round(canvas_height * 14 / panel_height)),
            f"Scene {index + 1}",
            fill="white",
            font=title_font,
        )
        max_caption_height = round(canvas_height * 0.18)
        text_bbox = draw.textbbox((0, 0), "Ag", font=body_font)
        glyph_height = text_bbox[3] - text_bbox[1]
        caption_padding = max(24, round(canvas_height * 0.015))
        line_height = max(
            glyph_height + caption_padding // 2,
            round(canvas_height * 0.035),
        )
        margin_x = round(canvas_width * 12 / panel_width)
        text_x = round(canvas_width * 24 / panel_width)
        lines = wrap_caption(
            scene["narration_text"],
            draw,
            body_font,
            canvas_width - 2 * text_x,
        )
        visible_lines = max(
            1,
            min(
                len(lines),
                max(1, (max_caption_height - 2 * caption_padding) // line_height),
            ),
        )
        lines = lines[-visible_lines:]
        box_height = caption_box_height(
            len(lines),
            line_height,
            caption_padding,
            max_caption_height,
        )
        margin_y = round(canvas_height * 12 / panel_height)
        draw.rectangle(
            (margin_x, canvas_height - box_height - margin_y, canvas_width - margin_x, canvas_height - margin_y),
            fill="#000000",
        )
        for line_number, text in enumerate(lines):
            draw.text(
                (
                    text_x,
                    canvas_height
                    - box_height
                    + caption_padding
                    - text_bbox[1]
                    + line_number * line_height,
                ),
                text,
                fill="white",
                font=body_font,
            )
        panel = panel.convert("RGB").resize(
            (panel_width, panel_height),
            Image.Resampling.LANCZOS,
        )
        sheet.paste(panel, (x, y))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output_path, format="PNG")


def write_manifest(script: dict[str, Any], project_dir: Path) -> None:
    scenes = []
    for scene in script["scenes"]:
        scenes.append(
            {
                "id": scene["id"],
                "duration_sec": None,
                "narration_word_count": len(scene["narration_text"].split()),
                "render_mode": "mock",
            }
        )
    manifest = {"render_mode": "mock", "audio": None, "scenes": scenes}
    (project_dir / "build_manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
