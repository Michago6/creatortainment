"""Tests storyboard geometry and pixel-based caption wrapping for both orientations."""

from PIL import Image, ImageDraw, ImageFont

from creatortainment.render.mock import (
    caption_box_height,
    storyboard_panel_size,
    storyboard_sheet_size,
    wrap_caption,
)


def test_vertical_storyboard_panels_preserve_9_by_16() -> None:
    """Vertical scripts produce panels with the canonical 9:16 ratio."""
    assert storyboard_panel_size((1080, 1920)) == (360, 640)


def test_horizontal_storyboard_panels_preserve_16_by_9() -> None:
    """Horizontal scripts produce panels with the canonical 16:9 ratio."""
    assert storyboard_panel_size((1920, 1080), 540) == (540, 304)


def test_sheet_size_accounts_for_scene_count_and_orientation() -> None:
    """Contact sheets keep landscape previews readable and vertical layouts compact."""
    assert storyboard_sheet_size((1920, 1080), 6) == (1440, 1215)
    assert storyboard_sheet_size((1080, 1920), 3) == (1080, 640)


def test_horizontal_caption_wrapping_uses_available_width() -> None:
    """Horizontal captions fit more words per line than the old fixed 30-character rule."""
    image = Image.new("RGB", (1920, 1080))
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 32)
    text = "Look at all these arithmetic logic units executing threads simultaneously."
    lines = wrap_caption(text, draw, font, max_width=1000)
    assert len(lines) == 2
    assert lines[0] == "Look at all these arithmetic logic units executing threads"


def test_caption_box_includes_text_block_and_bottom_padding() -> None:
    """Caption height leaves room below the final rendered text line."""
    assert caption_box_height(2, line_height=48, padding=24, max_height=400) == 144
