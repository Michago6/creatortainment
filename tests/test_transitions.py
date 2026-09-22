"""Focused transition geometry and mask tests."""

from __future__ import annotations

import numpy as np
import pytest
from moviepy import ColorClip

from creatortainment.render.moviepy_scene import _apply_scene_transition_effects


def test_soft_push_keeps_incoming_scene_static_and_unmasked() -> None:
    """The incoming soft-push scene is fully opaque and stationary."""
    clip = ColorClip((100, 60), color=(255, 0, 0), duration=1.0)
    try:
        soft = _apply_scene_transition_effects(
            clip,
            {
                "type": "push", "direction": "left", "style": "soft",
                "duration_sec": 0.5,
            },
            None,
            (100, 60),
        )
        assert soft.pos(0.0) == (0.0, 0.0)
        assert soft.pos(0.25) == (0.0, 0.0)
        assert soft.pos(0.5) == (0.0, 0.0)
        assert soft.mask is None
    finally:
        clip.close()


def test_soft_push_masks_only_outgoing_scene_with_moving_feather() -> None:
    """The outgoing mask peels while the outgoing clip stays stationary."""
    clip = ColorClip((100, 60), color=(255, 0, 0), duration=1.0)
    try:
        soft = _apply_scene_transition_effects(
            clip,
            None,
            {
                "type": "push", "direction": "left", "style": "soft",
                "duration_sec": 0.5,
            },
            (100, 60),
        )
        for time in (0.0, 0.25, 0.5, 0.6, 0.7, 0.75, 0.8, 0.9, 1.0):
            assert soft.pos(time) == pytest.approx((0.0, 0.0))
        start = soft.mask.get_frame(0.5)[30]
        middle = soft.mask.get_frame(0.75)[30]
        end = soft.mask.get_frame(1.0)[30]
        assert np.allclose(start, 1.0)
        assert middle[0] == pytest.approx(1.0)
        assert middle[99] == pytest.approx(0.0)
        assert 0.0 < middle[50] < 1.0
        assert np.allclose(end, 0.0)
    finally:
        clip.close()


def test_soft_push_right_direction_mirrors_the_outgoing_mask() -> None:
    clip = ColorClip((100, 60), color=(255, 0, 0), duration=1.0)
    try:
        soft = _apply_scene_transition_effects(
            clip,
            None,
            {
                "type": "push", "direction": "right", "style": "soft",
                "duration_sec": 0.5,
            },
            (100, 60),
        )
        middle = soft.mask.get_frame(0.75)[30]
        assert middle[0] == pytest.approx(0.0)
        assert middle[99] == pytest.approx(1.0)
        assert 0.0 < middle[50] < 1.0
    finally:
        clip.close()


def test_hard_push_has_no_feather_mask() -> None:
    """Hard push remains a plain slide without an incoming alpha mask."""
    clip = ColorClip((100, 60), color=(255, 0, 0), duration=1.0)
    try:
        hard = _apply_scene_transition_effects(
            clip,
            {
                "type": "push",
                "direction": "left",
                "style": "hard",
                "duration_sec": 0.5,
            },
            None,
            (100, 60),
        )
        assert hard.mask is None
        positions = [hard.pos(time) for time in (0.0, 0.1, 0.25, 0.4, 0.5)]
        assert positions[0] == pytest.approx((100.0, 0.0))
        assert positions[-1] == pytest.approx((0.0, 0.0))
        assert len(set(positions)) > 2
    finally:
        clip.close()


def test_hard_outgoing_push_still_moves_offscreen() -> None:
    clip = ColorClip((100, 60), color=(255, 0, 0), duration=1.0)
    try:
        hard = _apply_scene_transition_effects(
            clip,
            None,
            {
                "type": "push",
                "direction": "left",
                "style": "hard",
                "duration_sec": 0.5,
            },
            (100, 60),
        )
        positions = [hard.pos(time) for time in (0.5, 0.6, 0.75, 0.9, 1.0)]
        assert positions[0] == pytest.approx((0.0, 0.0))
        assert positions[-1] == pytest.approx((-100.0, 0.0))
        assert len(set(positions)) > 2
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
