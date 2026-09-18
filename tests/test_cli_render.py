"""Tests that CLI preview and full-render paths choose exact output dimensions."""

from __future__ import annotations

from moviepy import ColorClip

from creatortainment.cli import prepare_render_clip


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
    clip = ColorClip((1920, 1080), color=(0, 0, 0), duration=0.1)
    try:
        encoded = prepare_render_clip(clip, (1920, 1080), preview=True)
        assert encoded.size == (480, 270)
        encoded.close()
    finally:
        clip.close()
