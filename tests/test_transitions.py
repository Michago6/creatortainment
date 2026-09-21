"""Focused transition geometry and mask tests."""

from __future__ import annotations

import numpy as np
import pytest
from moviepy import ColorClip

from creatortainment.render.moviepy_scene import (
    _apply_scene_transition_effects,
    _apply_push_transition,
)


def test_soft_push_feathers_the_incoming_leading_edge() -> None:
    """Soft push masks retain a real 0-to-1 gradient in clip-local space."""
    resolution = (100, 60)
    clip = ColorClip(resolution, color=(255, 0, 0), duration=1.0)
    try:
        soft = _apply_push_transition(
            clip,
            {
                "direction": "left",
                "style": "soft",
                "duration_sec": 0.5,
                "feather_frac": 0.2,
            },
            0.5,
            resolution,
        )
        mask = soft.mask.get_frame(0.25)[30]
        assert mask[0] == 0.0
        assert 0.0 < mask[10] < 1.0
        assert mask[20] == 1.0
        assert np.allclose(mask, soft.mask.get_frame(0.0)[30])
    finally:
        clip.close()


def test_soft_push_creates_an_overlap_band_for_the_fade() -> None:
    """Soft push overlaps the outgoing edge instead of fading into empty canvas."""
    clip = ColorClip((100, 60), color=(255, 0, 0), duration=1.0)
    try:
        hard = _apply_scene_transition_effects(
            clip,
            {"type": "push", "direction": "right", "style": "hard", "duration_sec": 0.5},
            None,
            (100, 60),
        )
        soft = _apply_scene_transition_effects(
            clip,
            {
                "type": "push",
                "direction": "right",
                "style": "soft",
                "duration_sec": 0.5,
                "feather_frac": 0.2,
            },
            None,
            (100, 60),
        )
        assert hard.pos(0.25)[0] == -50.0
        assert soft.pos(0.25)[0] == -25.0
    finally:
        clip.close()


def test_hard_push_has_no_feather_mask() -> None:
    """Hard push remains a plain slide without an incoming alpha mask."""
    clip = ColorClip((100, 60), color=(255, 0, 0), duration=1.0)
    try:
        hard = _apply_push_transition(
            clip,
            {"direction": "left", "style": "hard", "duration_sec": 0.5},
            0.5,
            (100, 60),
        )
        assert hard.mask is None
        assert hard.pos(0.0) != hard.pos(0.5)
    finally:
        clip.close()


def test_dual_role_scene_preserves_entrance_middle_and_exit_transforms() -> None:
    """A scene's incoming and outgoing transitions each own only their window."""
    clip = ColorClip((100, 60), color=(255, 0, 0), duration=2.0)
    try:
        transformed = _apply_scene_transition_effects(
            clip,
            {"type": "zoom_out", "duration_sec": 0.5, "zoom_scale": 1.4},
            {"type": "push", "direction": "left", "style": "hard", "duration_sec": 0.5},
            (100, 60),
        )
        entrance_size = transformed.get_frame(0).shape[1::-1]
        middle_size = transformed.get_frame(1).shape[1::-1]
        exit_size = transformed.get_frame(1.75).shape[1::-1]
        assert entrance_size == (140, 84)
        assert middle_size == (100, 60)
        assert exit_size == (100, 60)
        assert transformed.pos(0) == pytest.approx((-20.0, -12.0))
        assert transformed.pos(0.25) == pytest.approx((-10.0, -6.0))
        assert transformed.pos(1.0) == pytest.approx((0.0, 0.0))
        assert transformed.pos(1.75) == pytest.approx((-50.0, 0.0))
        assert transformed.pos(2.0) == pytest.approx((-100.0, 0.0))
    finally:
        clip.close()
