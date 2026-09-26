"""Tests mapping raw narration cues onto the final paused video timeline."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from creatortainment.render.timeline import (
    build_scene_final_offsets,
    resolve_cue_to_final_video_time,
)


ROOT = Path(__file__).parents[1]


def _script() -> dict:
    return json.loads(
        (ROOT / "scripts/testing_scripts/example_script_extended.json").read_text(
            encoding="utf-8"
        )
    )


def _manifest() -> dict:
    return json.loads(
        (
            ROOT
            / "projects/understanding_gpu_architecture/build_manifests/example_script_extended.json"
        ).read_text(encoding="utf-8")
    )


def test_cue_mapping_includes_early_scene_pause_offset() -> None:
    """A cue in scene two lands after scene one and scene two's pause."""
    script = _script()
    manifest = _manifest()
    offsets = build_scene_final_offsets(script, manifest)
    scene_index = 1
    scene = script["scenes"][scene_index]
    scene_manifest = manifest["scenes"][scene_index]
    trigger_index = 2

    expected = (
        offsets[scene_index].narration_start_sec
        + manifest["word_timestamps"][
            scene_manifest["word_offset"] + trigger_index
        ]["start"]
        - scene_manifest["start_time_sec"]
    )
    assert resolve_cue_to_final_video_time(
        scene,
        trigger_index,
        manifest,
        offsets,
    ) == pytest.approx(expected)


def test_cue_mapping_accumulates_late_scene_pauses() -> None:
    """A late-scene cue includes every preceding scene duration and pause."""
    script = _script()
    manifest = _manifest()
    offsets = build_scene_final_offsets(script, manifest)
    scene_index = 4
    scene = script["scenes"][scene_index]
    scene_manifest = manifest["scenes"][scene_index]
    trigger_index = 2

    prior_duration_and_pauses = sum(
        float(item["duration_sec"])
        + (float(script["scenes"][index].get("pause_before_sec", 0.0)) if index > 0 else 0.0)
        for index, item in enumerate(manifest["scenes"][:scene_index])
    )
    expected = (
        prior_duration_and_pauses
        + float(scene.get("pause_before_sec", 0.0))
        + manifest["word_timestamps"][
            scene_manifest["word_offset"] + trigger_index
        ]["start"]
        - scene_manifest["start_time_sec"]
    )
    assert resolve_cue_to_final_video_time(
        scene,
        trigger_index,
        manifest,
        offsets,
    ) == pytest.approx(expected)
