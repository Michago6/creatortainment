"""Tests shared final-video scene offset calculation."""

import pytest

from creatortainment.render.timeline import build_scene_final_offsets


def test_scene_offsets_include_prior_and_current_pauses() -> None:
    """Narration placement matches the existing pause-prefixed assembly order."""
    script = {
        "scenes": [
            {"id": "one", "pause_before_sec": 9.0},
            {"id": "two", "pause_before_sec": 0.4},
            {"id": "three", "pause_before_sec": 0.3},
        ]
    }
    manifest = {
        "scenes": [
            {"duration_sec": 2.0},
            {"duration_sec": 3.0},
            {"duration_sec": 4.0},
        ]
    }
    offsets = build_scene_final_offsets(script, manifest)
    assert offsets[0].final_start_sec == 0.0
    assert offsets[0].narration_start_sec == 0.0
    assert offsets[1].final_start_sec == 2.0
    assert offsets[1].narration_start_sec == 2.4
    assert offsets[2].final_start_sec == 5.4
    assert offsets[2].narration_start_sec == 5.7


def test_transition_overlaps_reduce_total_duration_after_pauses() -> None:
    """Transition duration is subtracted independently from scene pauses."""
    script = {
        "scenes": [
            {"id": "one", "pause_before_sec": 0.0, "transition_in": None},
            {
                "id": "two",
                "pause_before_sec": 0.3,
                "transition_in": {"type": "crossfade", "duration_sec": 0.4},
            },
            {
                "id": "three",
                "pause_before_sec": 0.2,
                "transition_in": {"type": "zoom_out", "duration_sec": 0.5},
            },
        ]
    }
    manifest = {
        "scenes": [
            {"duration_sec": 2.0},
            {"duration_sec": 3.0},
            {"duration_sec": 4.0},
        ]
    }
    offsets = build_scene_final_offsets(script, manifest)
    naive_duration = 2.0 + 3.0 + 4.0 + 0.3 + 0.2
    expected_duration = naive_duration - 0.4 - 0.5
    actual_duration = offsets[-1].final_start_sec + offsets[-1].unit_duration_sec
    assert actual_duration == pytest.approx(expected_duration)
