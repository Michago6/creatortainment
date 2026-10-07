"""Tests slicing the active project narration onto an individual MoviePy scene."""

from __future__ import annotations

import json
from pathlib import Path

from creatortainment.render.moviepy_scene import attach_scene_narration, build_static_scene_clip


ROOT = Path(__file__).parents[2]
ASSETS = ROOT / "testing/assets"
PROJECT = ROOT / "projects/understanding_gpu_architecture"


def test_scene_narration_slice_matches_manifest_duration() -> None:
    """A scene audio slice duration matches its manifest start/end interval."""
    script = json.loads(
        (ROOT / "testing/scripts/example_script.json").read_text(encoding="utf-8")
    )
    manifest = json.loads((PROJECT / "build_manifest.json").read_text(encoding="utf-8"))
    scene_manifest = manifest["scenes"][0]
    clip = build_static_scene_clip(script, script["scenes"][0], scene_manifest, ASSETS)
    audio = None
    try:
        clip = attach_scene_narration(clip, scene_manifest, manifest, PROJECT)
        audio = clip.audio
        expected = scene_manifest["end_time_sec"] - scene_manifest["start_time_sec"]
        assert abs(audio.duration - expected) <= 0.05
    finally:
        if audio is not None:
            audio.close()
        clip.close()
