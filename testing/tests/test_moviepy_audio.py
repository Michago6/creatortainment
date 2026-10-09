"""Tests slicing the active project narration onto an individual MoviePy scene."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from moviepy import AudioClip, ColorClip

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


@pytest.mark.parametrize(
    ("requested_end", "audio_duration", "expected_end"),
    [
        (52.192653, 52.19, 52.19),
        (2.0, 2.0, 2.0),
        (2.049, 2.0, 2.0),
    ],
)
def test_global_audio_subclip_normalizes_safe_endpoint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    requested_end: float,
    audio_duration: float,
    expected_end: float,
) -> None:
    audio_path = tmp_path / "narration.mp3"
    audio_path.write_bytes(b"cached")
    source = AudioClip(
        lambda t: [0.0, 0.0],
        duration=audio_duration,
        fps=44100,
    )
    monkeypatch.setattr(
        "creatortainment.render.moviepy_scene.AudioFileClip",
        lambda _path: source,
    )
    scene_clip = ColorClip((32, 32), color=(0, 0, 0), duration=requested_end)
    manifest = {
        "narration_audio_path": str(audio_path),
        "scenes": [],
    }
    scene = {
        "start_time_sec": 0.0,
        "end_time_sec": requested_end,
    }
    attached = attach_scene_narration(scene_clip, scene, manifest, tmp_path)
    try:
        assert attached.audio.duration == pytest.approx(expected_end)
    finally:
        attached.close()


def test_global_audio_subclip_rejects_overrun_beyond_tolerance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    audio_path = tmp_path / "narration.mp3"
    audio_path.write_bytes(b"cached")
    source = AudioClip(lambda t: [0.0, 0.0], duration=2.0, fps=44100)
    monkeypatch.setattr(
        "creatortainment.render.moviepy_scene.AudioFileClip",
        lambda _path: source,
    )
    scene_clip = ColorClip((32, 32), color=(0, 0, 0), duration=2.2)
    with pytest.raises(ValueError, match="audio=2.000s"):
        attach_scene_narration(
            scene_clip,
            {"start_time_sec": 0.0, "end_time_sec": 2.2},
            {"narration_audio_path": str(audio_path), "scenes": []},
            tmp_path,
        )
    scene_clip.close()


def test_earlier_scene_audio_boundary_is_not_normalized(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    audio_path = tmp_path / "narration.mp3"
    audio_path.write_bytes(b"cached")
    source = AudioClip(lambda t: [0.0, 0.0], duration=4.0, fps=44100)
    monkeypatch.setattr(
        "creatortainment.render.moviepy_scene.AudioFileClip",
        lambda _path: source,
    )
    scene_clip = ColorClip((32, 32), color=(0, 0, 0), duration=2.0)
    attached = attach_scene_narration(
        scene_clip,
        {"start_time_sec": 1.0, "end_time_sec": 2.0},
        {"narration_audio_path": str(audio_path), "scenes": []},
        tmp_path,
    )
    try:
        assert attached.audio.duration == pytest.approx(1.0)
    finally:
        attached.close()
