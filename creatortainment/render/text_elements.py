"""Deterministic RGBA rendering for authored text elements."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont


FONT_FALLBACKS = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
)


def resolve_text_font(requested: Any, size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [requested] if isinstance(requested, str) else []
    candidates.extend(FONT_FALLBACKS)
    for candidate in candidates:
        if Path(candidate).is_file():
            return ImageFont.truetype(candidate, size)
    return ImageFont.load_default()


def text_element_image(element: Any) -> Image.Image:
    """Render text with explicit newlines; no implicit wrapping is performed."""
    text = str(element.get("text", ""))
    style = element.get("text_style") or {}
    size = max(1, int(style.get("font_size", 48)))
    font = resolve_text_font(style.get("font"), size)
    padding = max(0, int(style.get("padding", 0)))
    stroke_width = max(0, int(style.get("stroke_width", 0)))
    alignment = str(style.get("alignment", "left"))
    bbox = ImageDraw.Draw(Image.new("L", (1, 1))).multiline_textbbox(
        (0, 0), text, font=font, align=alignment, stroke_width=stroke_width
    )
    width = max(1, round(bbox[2] - bbox[0] + padding * 2))
    height = max(1, round(bbox[3] - bbox[1] + padding * 2))
    background = style.get("background_color", "#000000")
    opacity = max(0, min(255, round(float(style.get("background_opacity", 0.0)) * 255)))
    image = Image.new("RGBA", (width, height), (*_rgb(background), opacity))
    draw = ImageDraw.Draw(image)
    draw.multiline_text(
        (padding - bbox[0], padding - bbox[1]),
        text,
        font=font,
        fill=style.get("color", "#ffffff"),
        stroke_fill=style.get("stroke_color", "#000000"),
        stroke_width=stroke_width,
        align=alignment,
    )
    return image


def _rgb(value: Any) -> tuple[int, int, int]:
    # PIL accepts named and hex colors; this helper only needs a valid RGB
    # background while retaining a useful error for malformed authored values.
    from PIL import ImageColor

    rgb = ImageColor.getrgb(str(value))
    return tuple(rgb[:3])
