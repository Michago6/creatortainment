"""Tests shared final-video scene offset calculation."""

import pytest
from moviepy import AudioClip, CompositeAudioClip

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


def test_transition_overlaps_visuals_without_changing_logical_timing() -> None:
    """Transitions start visuals early but preserve sequential logical timing."""
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
    expected_duration = naive_duration
    actual_duration = offsets[-1].final_start_sec + offsets[-1].unit_duration_sec
    assert actual_duration == pytest.approx(expected_duration)
    assert offsets[1].final_start_sec == pytest.approx(2.0)
    assert offsets[1].visual_start_sec == pytest.approx(1.6)
    assert offsets[1].narration_start_sec == pytest.approx(2.3)
    assert offsets[2].final_start_sec == pytest.approx(5.3)
    assert offsets[2].visual_start_sec == pytest.approx(4.8)
    assert offsets[2].narration_start_sec == pytest.approx(5.5)


@pytest.mark.parametrize(
    "transition",
    [
        None,
        {"type": "crossfade", "duration_sec": 0.4},
        {"type": "zoom_out", "duration_sec": 0.5, "zoom_scale": 1.3},
        {"type": "push", "direction": "left", "style": "hard", "duration_sec": 0.6},
        {"type": "push", "direction": "right", "style": "soft", "duration_sec": 0.7},
    ],
)
def test_all_transition_types_preserve_sequential_audio_boundaries(
    transition: dict | None,
) -> None:
    script = {
        "scenes": [
            {"id": "one", "pause_before_sec": 0.0, "transition_in": None},
            {"id": "two", "pause_before_sec": 0.25, "transition_in": transition},
        ]
    }
    manifest = {"scenes": [{"duration_sec": 2.0}, {"duration_sec": 3.0}]}
    offsets = build_scene_final_offsets(script, manifest)
    assert offsets[1].final_start_sec == pytest.approx(2.0)
    assert offsets[1].narration_start_sec == pytest.approx(2.25)
    assert offsets[0].narration_end_sec <= offsets[1].narration_start_sec
    expected_visual_start = 2.0 - (
        0.0 if transition is None else transition["duration_sec"]
    )
    assert offsets[1].visual_start_sec == pytest.approx(expected_visual_start)


def test_pause_changes_audio_start_but_not_visual_transition_window() -> None:
    base = {
        "scenes": [
            {"id": "one", "pause_before_sec": 0.0},
            {
                "id": "two",
                "pause_before_sec": 0.2,
                "transition_in": {"type": "zoom_out", "duration_sec": 0.5},
            },
        ]
    }
    manifest = {"scenes": [{"duration_sec": 2.0}, {"duration_sec": 3.0}]}
    paused = build_scene_final_offsets(base, manifest)
    base["scenes"][1]["pause_before_sec"] = 0.8
    longer_pause = build_scene_final_offsets(base, manifest)
    assert paused[1].visual_start_sec == pytest.approx(1.5)
    assert longer_pause[1].visual_start_sec == pytest.approx(1.5)
    assert paused[1].narration_start_sec == pytest.approx(2.2)
    assert longer_pause[1].narration_start_sec == pytest.approx(2.8)


def test_transition_visual_overlap_does_not_overlap_synthetic_audio_markers() -> None:
    script = {
        "scenes": [
            {"id": "one", "pause_before_sec": 0.0},
            {
                "id": "two",
                "pause_before_sec": 0.0,
                "transition_in": {"type": "zoom_out", "duration_sec": 0.5},
            },
        ]
    }
    manifest = {"scenes": [{"duration_sec": 2.0}, {"duration_sec": 1.0}]}
    offsets = build_scene_final_offsets(script, manifest)
    sample_rate = 1_000
    first = AudioClip(
        lambda t: [1.0, 1.0],
        duration=2.0,
        fps=sample_rate,
    ).with_start(offsets[0].final_start_sec)
    second = AudioClip(
        lambda t: [2.0, 2.0],
        duration=1.0,
        fps=sample_rate,
    ).with_start(offsets[1].final_start_sec)
    mixed = CompositeAudioClip([first, second])
    try:
        assert offsets[1].visual_start_sec == pytest.approx(1.5)
        assert mixed.get_frame(1.75)[0] == pytest.approx(1.0)
        assert mixed.get_frame(2.0)[0] == pytest.approx(2.0)
    finally:
        mixed.close()
        first.close()
        second.close()


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
    assert offsets[1].final_start_sec == pytest.approx(4.5)
    assert offsets[-1].final_start_sec + offsets[-1].unit_duration_sec == pytest.approx(7.8)
