"""Tests storyboard geometry and pixel-based caption wrapping for both orientations."""

from PIL import Image, ImageDraw, ImageFont

import creatortainment.render.mock as storyboard_renderer
from creatortainment.render.mock import (
    _storyboard_caption_layout,
    _storyboard_caption_tracks,
    caption_box_height,
    render_storyboard,
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


def test_storyboard_caption_background_is_actually_60_percent_opaque(
    tmp_path,
    monkeypatch,
) -> None:
    background = Image.new("RGB", (1080, 1920), (100, 150, 200))
    background_path = tmp_path / "background.png"
    background.save(background_path)
    script = {
        "project": {"resolution": [1080, 1920]},
        "asset_registry": {
            "background": {"path": str(background_path), "generate": None},
        },
        "scenes": [
            {
                "bg": "background",
                "narration_text": "Short caption",
                "elements": [],
            }
        ],
    }
    monkeypatch.setattr(
        storyboard_renderer,
        "_asset_path",
        lambda _registry, _key, _assets_root: background_path,
    )
    output = tmp_path / "storyboard.png"

    render_storyboard(script, tmp_path / "assets", output)

    with Image.open(output) as rendered:
        pixel = rendered.getpixel((rendered.width // 2, rendered.height - 30))
    assert pixel == (40, 60, 80)


def test_storyboard_uses_inherited_background_for_later_scenes(tmp_path, monkeypatch) -> None:
    background = Image.new("RGB", (1080, 1920), (100, 150, 200))
    background_path = tmp_path / "background.png"
    background.save(background_path)
    script = {
        "project": {"resolution": [1080, 1920]},
        "asset_registry": {
            "background": {"path": str(background_path), "generate": None},
        },
        "scenes": [
            {"bg": "background", "narration_text": "First", "elements": []},
            {"narration_text": "Inherited", "elements": []},
        ],
    }
    paths: list[str] = []
    monkeypatch.setattr(
        storyboard_renderer,
        "_asset_path",
        lambda _registry, key, _assets_root: paths.append(key) or background_path,
    )

    render_storyboard(script, tmp_path / "assets", tmp_path / "storyboard.png")

    assert paths == ["background", "background"]


def test_long_storyboard_caption_preserves_beginning_and_end() -> None:
    image = Image.new("RGBA", (1080, 1920))
    draw = ImageDraw.Draw(image)
    text = (
        "Beginning of the narration remains visible while this deliberately "
        "long caption continues with enough words to exceed three lines and "
        "ends with the final narration phrase."
    )

    _, lines, _, _ = _storyboard_caption_layout(
        text,
        draw,
        (1080, 1920),
        (360, 640),
        max_caption_height=round(1920 * 0.18),
        caption_padding=max(24, round(1920 * 0.015)),
    )

    assert "Beginning" in lines[0]
    assert "phrase." in lines[-1]
    assert " ".join(lines) == text


def test_short_storyboard_caption_keeps_existing_size_and_layout() -> None:
    image = Image.new("RGBA", (1080, 1920))
    draw = ImageDraw.Draw(image)
    text = "A short storyboard caption stays unchanged."

    font, lines, line_height, box_height = _storyboard_caption_layout(
        text,
        draw,
        (1080, 1920),
        (360, 640),
        max_caption_height=round(1920 * 0.18),
        caption_padding=max(24, round(1920 * 0.015)),
    )

    assert font.size == 48
    assert lines == ["A short storyboard caption stays", "unchanged."]
    assert line_height > 0
    assert box_height == round(1920 * 0.18)


def _multi_voice_storyboard_script() -> dict:
    return {
        "project": {
            "resolution": [1080, 1920],
            "voice_id": "voice-default",
        },
        "asset_registry": {"background": {"path": "assets/backgrounds/default_studio.jpg"}},
        "scenes": [
            {
                "id": "dialogue",
                "bg": "background",
                "narration_segments": [
                    {"id": "a", "text": "First speaker line.", "voice_id": "voice-a"},
                    {"id": "b", "text": "Second speaker line."},
                ],
                "elements": [],
            }
        ],
    }


def test_segment_only_storyboard_uses_separate_effective_voice_tracks() -> None:
    tracks = _storyboard_caption_tracks(_multi_voice_storyboard_script(), _multi_voice_storyboard_script()["scenes"][0])
    assert tracks == [
        ("voice-a", "First speaker line."),
        ("voice-default", "Second speaker line."),
    ]


def test_multi_voice_storyboard_renders_stacked_tracks_and_keeps_bounds(
    tmp_path,
    monkeypatch,
) -> None:
    background = Image.new("RGB", (1080, 1920), (100, 150, 200))
    background_path = tmp_path / "background.png"
    background.save(background_path)
    script = _multi_voice_storyboard_script()
    monkeypatch.setattr(
        storyboard_renderer,
        "_asset_path",
        lambda _registry, _key, _assets_root: background_path,
    )

    output = tmp_path / "storyboard.png"
    render_storyboard(script, tmp_path / "assets", output)

    with Image.open(output) as rendered:
        assert rendered.size == (1080, 1920)
        assert rendered.getbbox() == (0, 0, 1080, 1920)

    tracks = _storyboard_caption_tracks(script, script["scenes"][0])
    image = Image.new("RGBA", (1080, 1920))
    draw = ImageDraw.Draw(image)
    max_width = 1080 - 2 * round(1080 * 24 / 360)
    for _voice_id, text in tracks:
        lines = wrap_caption(text, draw, ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 48
        ), max_width)
        assert all(draw.textlength(line, font=ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 48
        )) <= max_width for line in lines)
