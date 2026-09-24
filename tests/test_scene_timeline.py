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


@pytest.mark.parametrize("extra_duration", [None, 0.0])
def test_missing_or_zero_extra_duration_preserves_scene_timing(
    extra_duration: float | None,
) -> None:
    scene = {"id": "one", "pause_before_sec": 0.0}
    if extra_duration is not None:
        scene["extra_duration_sec"] = extra_duration
    offsets = build_scene_final_offsets(
        {"scenes": [scene]},
        {"scenes": [{"duration_sec": 2.5}]},
    )
    assert offsets[0].unit_duration_sec == pytest.approx(2.5)
    assert offsets[0].narration_end_sec == pytest.approx(2.5)


def test_positive_extra_duration_extends_only_the_scene_visual_unit() -> None:
    offsets = build_scene_final_offsets(
        {
            "scenes": [
                {"id": "one", "pause_before_sec": 0.0, "extra_duration_sec": 2.0},
                {
                    "id": "two",
                    "pause_before_sec": 0.3,
                    "transition_in": {"type": "crossfade", "duration_sec": 0.4},
                },
            ]
        },
        {
            "scenes": [
                {"duration_sec": 2.5},
                {"duration_sec": 3.0},
            ]
        },
    )
    assert offsets[0].narration_end_sec == pytest.approx(2.5)
    assert offsets[0].unit_duration_sec == pytest.approx(4.5)
    assert offsets[1].final_start_sec == pytest.approx(4.1)
    assert offsets[-1].final_start_sec + offsets[-1].unit_duration_sec == pytest.approx(7.4)
