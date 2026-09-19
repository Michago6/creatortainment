"""Tests final narration, music, and SFX audio attachment."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from moviepy import AudioClip

from creatortainment.audio.mixing import build_final_audio_mix
from creatortainment.render.moviepy_scene import build_full_video_clip


ROOT = Path(__file__).parents[1]
PROJECT = ROOT / "projects/understanding_gpu_architecture"
ASSETS = ROOT / "assets"


def _script() -> dict:
    return json.loads(
        (ROOT / "scripts/example_scripts/example_script.json").read_text(encoding="utf-8")
    )


def _manifest() -> dict:
    return json.loads(
        (PROJECT / "build_manifests/example_script.json").read_text(encoding="utf-8")
    )


def test_final_audio_mix_has_video_duration_and_three_layers() -> None:
    """The final mix combines narration, music, and SFX for the complete video."""
    script = _script()
    manifest = _manifest()
    duration = sum(float(item["duration_sec"]) for item in manifest["scenes"])
    duration += sum(float(scene.get("pause_before_sec", 0.0)) for scene in script["scenes"][1:])
    narration = AudioClip(
        frame_function=lambda t: [0.0, 0.0],
        duration=duration,
        fps=44100,
    )
    mixed = build_final_audio_mix(
        narration,
        script,
        manifest,
        ASSETS,
        PROJECT,
    )
    try:
        assert mixed.duration == pytest.approx(duration)
        assert len(mixed.clips) == 3
        assert mixed.clips[0] is narration
    finally:
        mixed.close()
        narration.close()


def test_full_video_replaces_scene_audio_with_final_mix() -> None:
    """Full assembly attaches a CompositeAudioClip rather than scene-only narration."""
    script = _script()
    manifest = _manifest()
    clip = build_full_video_clip(script, manifest, ASSETS, PROJECT)
    try:
        assert clip.audio is not None
        assert len(clip.audio.clips) == 3
    finally:
        clip.close()
