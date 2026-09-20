"""Tests that CLI preview and full-render paths choose exact output dimensions."""

from __future__ import annotations

from pathlib import Path

from moviepy import ColorClip

from creatortainment.cli import prepare_render_clip, scale_script_for_preview
from creatortainment.schema.validate import load_script


def test_non_preview_render_keeps_project_resolution() -> None:
    """A normal render keeps the clip at the exact project resolution."""
    clip = ColorClip((1920, 1080), color=(0, 0, 0), duration=0.1)
    try:
        encoded = prepare_render_clip(clip, (1920, 1080), preview=False)
        assert encoded.size == (1920, 1080)
    finally:
        clip.close()


def test_preview_render_uses_quarter_resolution() -> None:
    """Preview rendering explicitly scales the clip to one-quarter resolution."""
    clip = ColorClip((480, 270), color=(0, 0, 0), duration=0.1)
    try:
        encoded = prepare_render_clip(clip, (1920, 1080), preview=True)
        assert encoded.size == (480, 270)
    finally:
        clip.close()


def test_preview_script_scales_canvas_positions_and_caption_sizes() -> None:
    """Preview preparation scales visual coordinates before frame rendering."""
    script = {
        "project": {
            "resolution": [1920, 1080],
            "caption_style": {"font_size": 64},
        },
        "scenes": [
            {
                "caption_style": {"font_size": 76},
                "elements": [
                    {"keyframes": [{"pos": [1330, 470]}]},
                ],
            }
        ],
    }
    preview = scale_script_for_preview(script)
    assert preview["project"]["resolution"] == [480, 270]
    assert preview["project"]["caption_style"]["font_size"] == 16
    assert preview["scenes"][0]["caption_style"]["font_size"] == 19
    assert preview["scenes"][0]["elements"][0]["keyframes"][0]["pos"] == [332.5, 117.5]
    assert script["project"]["resolution"] == [1920, 1080]


def test_preview_script_scales_typed_models() -> None:
    """Preview preparation also scales the Pydantic-backed script model."""
    script = load_script(
        Path("scripts/example_scripts/example_script.json")
    )
    preview = scale_script_for_preview(script)
    assert preview["project"]["resolution"] == [270, 480]
    assert preview["project"]["caption_style"]["font_size"] == 16
