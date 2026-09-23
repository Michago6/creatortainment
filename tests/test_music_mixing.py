"""Tests background music event planning, ducking, and looping."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from creatortainment.audio.loudness import (
    LoudnessCache,
    compute_duck_gain,
    measure_loudness,
)
from creatortainment.audio.mixing import (
    _build_music_layers,
    build_background_music_track,
    build_music_segments,
    music_gain_at_time,
)
from creatortainment.render.timeline import build_scene_final_offsets


ROOT = Path(__file__).parents[1]
PROJECT = ROOT / "projects/understanding_gpu_architecture"
ASSETS = ROOT / "assets"


def _script() -> dict:
    return json.loads(
        (ROOT / "scripts/testing_scripts/example_script.json").read_text(
            encoding="utf-8"
        )
    )


def _manifest() -> dict:
    return json.loads(
        (PROJECT / "build_manifests/example_script.json").read_text(encoding="utf-8")
    )


def test_music_gain_stays_ducked_during_narration_and_pause() -> None:
    """The pause before scene two keeps the same ducked gain as narration."""
    script = _script()
    manifest = _manifest()
    offsets = build_scene_final_offsets(script, manifest)
    segment = build_music_segments(script, manifest, offsets)[0]
    intervals = [(item.narration_start_sec, item.narration_end_sec) for item in offsets]
    ducked = music_gain_at_time(segment, offsets[1].narration_start_sec + 1.0, 0.3, intervals)
    pause_time = offsets[1].final_start_sec + 0.1
    baseline = music_gain_at_time(segment, pause_time, 0.3, intervals)
    assert ducked == pytest.approx(0.3)
    assert baseline == pytest.approx(0.3)


def test_music_gain_accepts_timestamp_arrays() -> None:
    """Vectorized gain evaluation preserves timestamp shape."""
    script = _script()
    manifest = _manifest()
    offsets = build_scene_final_offsets(script, manifest)
    segment = build_music_segments(script, manifest, offsets)[0]
    intervals = [(item.narration_start_sec, item.narration_end_sec) for item in offsets]
    timestamps = np.array([
        offsets[0].narration_start_sec + 0.5,
        offsets[0].narration_start_sec + 1.0,
    ])
    gains = music_gain_at_time(segment, timestamps, 0.3, intervals)
    assert isinstance(gains, np.ndarray)
    assert gains.shape == timestamps.shape
    assert gains[0] == pytest.approx(0.15)
    assert gains[1] == pytest.approx(0.3)


def test_music_change_event_starts_new_segment() -> None:
    """A same-asset re-trigger does not create a new source segment."""
    script = _script()
    manifest = _manifest()
    segments = build_music_segments(script, manifest, build_scene_final_offsets(script, manifest))
    assert len(segments) == 1
    assert segments[0].asset == "music_main"
    assert segments[0].start_sec == pytest.approx(0.0)


def test_scene_duck_override_changes_music_gain() -> None:
    script = _script()
    script["scenes"][1]["duck_to_narration_pct"] = 0.7
    manifest = _manifest()
    offsets = build_scene_final_offsets(script, manifest)
    segments = build_music_segments(script, manifest, offsets)
    assert segments[0].duck_to_narration_pct == pytest.approx(0.4)
    assert len(segments) == 1

    first_scene_gain = music_gain_at_time(segments[0], segments[0].start_sec + 2.0, 0.4, [])
    second_scene_gain = music_gain_at_time(segments[0], offsets[1].final_start_sec + 0.1, 0.7, [])
    assert first_scene_gain != pytest.approx(second_scene_gain)


def test_same_asset_update_preserves_one_phase_continuous_layer() -> None:
    script = _script()
    script["scenes"][2]["bg_music"] = {
        "asset": "music_main",
        "trigger_word_index": 0,
        "fade_in_sec": 0.3,
    }
    manifest = _manifest()
    layers = _build_music_layers(script, manifest, build_scene_final_offsets(script, manifest))
    assert len(layers) == 1
    assert len(layers[0].transitions) == 2
    assert layers[0].transitions[1].time_sec > layers[0].start_sec


def test_different_asset_update_crossfades_layers() -> None:
    script = _script()
    script["scenes"][2]["bg_music"] = {
        "asset": "sfx_pop",
        "trigger_word_index": 0,
        "fade_in_sec": 0.3,
    }
    manifest = _manifest()
    layers = _build_music_layers(script, manifest, build_scene_final_offsets(script, manifest))
    assert len(layers) == 2
    outgoing, incoming = layers
    assert outgoing.asset == "music_main"
    assert incoming.asset == "sfx_pop"
    assert incoming.start_sec == pytest.approx(outgoing.transitions[-1].time_sec)
    assert outgoing.transitions[-1].to_duck_pct is None
    assert incoming.transitions[0].from_duck_pct is None


def test_music_phase_continues_across_null_scene_boundary() -> None:
    """A null bg_music scene does not restart the looped source audio."""
    script = _script()
    manifest = _manifest()
    offsets = build_scene_final_offsets(script, manifest)
    narration_loudness = measure_loudness(next((PROJECT / "narrations").glob("*.mp3")))
    track = build_background_music_track(
        script,
        manifest,
        ASSETS,
        PROJECT,
        narration_loudness,
        loudness_cache=LoudnessCache(),
    )
    source = None
    try:
        source = __import__("moviepy").AudioFileClip(
            str(ASSETS / "audio/monkeys_spinning_monkeys.mp3")
        )
        boundary = offsets[1].final_start_sec
        sample_time = boundary + 0.5
        source_time = sample_time % float(source.duration)
        duck_gain = compute_duck_gain(
            narration_loudness,
            measure_loudness(ASSETS / "audio/monkeys_spinning_monkeys.mp3"),
            0.4,
        )
        actual = track.get_frame(sample_time)
        expected = source.get_frame(source_time) * duck_gain
        restarted = source.get_frame(0.01) * duck_gain
        assert np.allclose(actual, expected, rtol=0.02, atol=0.001)
        assert not np.allclose(actual, restarted, rtol=0.02, atol=0.001)
    finally:
        if source is not None:
            source.close()
        track.close()


def test_stop_music_event_fades_to_silence() -> None:
    script = _script()
    script["scenes"][1]["bg_music"] = {
        "stop": True,
        "trigger_word_index": 0,
        "fade_in_sec": 0.5,
    }
    manifest = _manifest()
    offsets = build_scene_final_offsets(script, manifest)
    layers = _build_music_layers(script, manifest, offsets)
    stop_layer = layers[0]
    stop_transition = stop_layer.transitions[-1]
    assert stop_transition.to_duck_pct is None
    assert stop_transition.duration_sec == pytest.approx(0.5)
    segments = build_music_segments(script, manifest, offsets)
    stop_segment = next(segment for segment in segments if segment.target_gain == 0.0)
    start_gain = music_gain_at_time(
        stop_segment,
        stop_segment.start_sec,
        1.0,
        [],
    )
    end_gain = music_gain_at_time(
        stop_segment,
        stop_segment.start_sec + stop_segment.fade_in_sec,
        1.0,
        [],
    )
    assert start_gain == pytest.approx(1.0)
    assert end_gain == pytest.approx(0.0)


def test_music_restarts_only_after_stop() -> None:
    script = _script()
    script["scenes"][1]["bg_music"] = {
        "stop": True,
        "trigger_word_index": 0,
        "fade_in_sec": 0.5,
    }
    script["scenes"][2]["bg_music"] = {
        "asset": "music_main",
        "trigger_word_index": 0,
        "fade_in_sec": 0.25,
    }
    manifest = _manifest()
    layers = _build_music_layers(script, manifest, build_scene_final_offsets(script, manifest))
    assert len(layers) == 2
    assert layers[0].asset == layers[1].asset == "music_main"
    assert layers[1].start_sec > layers[0].start_sec
    assert layers[1].transitions[0].from_duck_pct is None


def test_real_music_asset_is_looped_to_full_required_stretch() -> None:
    """The real music asset is looped when its source duration is too short."""
    script = _script()
    manifest = _manifest()
    narration_loudness = measure_loudness(
        next((PROJECT / "narrations").glob("*.mp3"))
    )
    track = build_background_music_track(
        script,
        manifest,
        ASSETS,
        PROJECT,
        narration_loudness,
        loudness_cache=LoudnessCache(),
    )
    try:
        expected = build_scene_final_offsets(script, manifest)[-1].narration_end_sec
        source_duration = next(
            path.stat().st_size for path in [ASSETS / "audio/monkeys_spinning_monkeys.mp3"]
        )
        assert track.duration == pytest.approx(expected)
        assert source_duration > 0
        assert track.get_frame(expected - 0.01).shape[0] == 2
    finally:
        track.close()
