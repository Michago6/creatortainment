"""Tests background music event planning, ducking, and looping."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from creatortainment.audio.loudness import LoudnessCache, measure_loudness
from creatortainment.audio.mixing import (
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
        (ROOT / "scripts/example_scripts/example_script.json").read_text(
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
    ducked = music_gain_at_time(segment, offsets[0].narration_start_sec + 1.5, 0.3, intervals)
    pause_time = offsets[1].final_start_sec + 0.1
    baseline = music_gain_at_time(segment, pause_time, 0.3, intervals)
    assert ducked == pytest.approx(segment.volume * 0.3)
    assert baseline == pytest.approx(segment.volume * 0.3)


def test_music_gain_accepts_timestamp_arrays() -> None:
    """Vectorized gain evaluation preserves timestamp shape."""
    script = _script()
    manifest = _manifest()
    offsets = build_scene_final_offsets(script, manifest)
    segment = build_music_segments(script, manifest, offsets)[0]
    intervals = [(item.narration_start_sec, item.narration_end_sec) for item in offsets]
    timestamps = np.array([
        offsets[0].narration_start_sec + 0.5,
        offsets[1].final_start_sec + 0.1,
    ])
    gains = music_gain_at_time(segment, timestamps, 0.3, intervals)
    assert isinstance(gains, np.ndarray)
    assert gains.shape == timestamps.shape
    assert gains[0] < gains[1]


def test_music_change_event_starts_new_segment() -> None:
    """Scene three's music event starts a new target-volume segment."""
    script = _script()
    manifest = _manifest()
    segments = build_music_segments(script, manifest, build_scene_final_offsets(script, manifest))
    assert len(segments) == 2
    assert segments[0].asset == "music_main"
    assert segments[0].volume == pytest.approx(0.3)
    assert segments[1].start_sec > segments[0].start_sec
    assert segments[1].volume == pytest.approx(0.45)
    assert segments[1].fade_in_sec == pytest.approx(0.3)


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
