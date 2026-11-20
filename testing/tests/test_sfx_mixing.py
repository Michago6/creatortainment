"""Tests final-time SFX placement and one-shot mixing."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import numpy as np
import pytest

from creatortainment.audio.mixing import build_sfx_cues, build_sfx_track
from creatortainment.render.timeline import build_scene_final_offsets, resolve_cue_to_final_video_time


ROOT = Path(__file__).parents[2]
PROJECT = ROOT / "testing"
ASSETS = ROOT / "testing/assets"


def _script() -> dict:
    return json.loads(
        (ROOT / "testing/scripts/example_script.json").read_text(encoding="utf-8")
    )


def _manifest() -> dict:
    return json.loads(
        (ROOT / "testing/fixtures/manifests/example_script.json").read_text(encoding="utf-8")
    )


def test_real_scene_one_sfx_cues_use_shared_final_time_mapping() -> None:
    """Both real scene-one pop cues resolve to the Checkpoint B timestamps."""
    script = _script()
    manifest = _manifest()
    offsets = build_scene_final_offsets(script, manifest)
    cues = build_sfx_cues(script, manifest, offsets)
    scene = script["scenes"][0]
    expected = [
        resolve_cue_to_final_video_time(scene, item["trigger_word_index"], manifest, offsets)
        for item in scene["sfx"]
    ]
    assert [cue.asset for cue in cues[:2]] == ["sfx_pop", "sfx_pop"]
    assert [cue.time_sec for cue in cues[:2]] == pytest.approx(expected)


def test_overlapping_sfx_are_composited() -> None:
    """Two simultaneous real SFX contribute to the same mixed frame."""
    script = _script()
    manifest = _manifest()
    script = copy.deepcopy(script)
    script["scenes"][0]["sfx"][1]["trigger_word_index"] = script["scenes"][0]["sfx"][0]["trigger_word_index"]
    offsets = build_scene_final_offsets(script, manifest)
    track = build_sfx_track(script, manifest, ASSETS, scene_offsets=offsets)
    try:
        time = build_sfx_cues(script, manifest, offsets)[0].time_sec + 0.1
        frame = track.get_frame(time)
        assert frame.shape == (2,)
        assert np.max(np.abs(frame)) > 0.0
    finally:
        track.close()


def test_sfx_is_clipped_at_final_video_end() -> None:
    """A cue near the end cannot extend the resulting track duration."""
    script = _script()
    manifest = _manifest()
    script = copy.deepcopy(script)
    final_scene = script["scenes"][-1]
    final_scene["sfx"] = [{"asset": "sfx_pop", "trigger_word_index": 0, "volume": 0.8}]
    offsets = build_scene_final_offsets(script, manifest)
    duration = offsets[-1].narration_end_sec
    final_scene["sfx"][0]["trigger_word_index"] = len(final_scene["narration_text"].split()) - 1
    track = build_sfx_track(script, manifest, ASSETS, scene_offsets=offsets)
    try:
        assert track.duration == pytest.approx(duration)
        assert track.get_frame(duration - 0.001).shape == (2,)
    finally:
        track.close()
