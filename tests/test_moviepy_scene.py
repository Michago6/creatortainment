"""Tests static MoviePy scene composition at manifest duration and script resolution."""

from __future__ import annotations

import json
from pathlib import Path

from creatortainment.render.moviepy_scene import (
    build_full_video_clip,
    build_static_scene_clip,
    caption_text_for_scene,
    resolve_caption_style,
)


ROOT = Path(__file__).parents[1]
ASSETS = ROOT / "assets"


def _script(name: str) -> dict:
    return json.loads(
        (ROOT / "scripts/example_scripts" / name).read_text(encoding="utf-8")
    )


def test_static_portrait_scene_uses_manifest_duration_and_resolution() -> None:
    """A portrait scene has the requested duration and 1080x1920 output size."""
    script = _script("example_script.json")
    manifest = {"duration_sec": 6.327}
    clip = build_static_scene_clip(script, script["scenes"][0], manifest, ASSETS)
    try:
        assert clip.duration == manifest["duration_sec"]
        assert clip.size == (1080, 1920)
        assert len(clip.clips) == len(script["scenes"][0]["elements"]) + 2
    finally:
        clip.close()


def test_static_landscape_scene_uses_manifest_duration_and_resolution() -> None:
    """A landscape scene has the requested duration and 1920x1080 output size."""
    script = _script("example_script_extended_horizontal.json")
    manifest = {"duration_sec": 5.0}
    clip = build_static_scene_clip(script, script["scenes"][0], manifest, ASSETS)
    try:
        assert clip.duration == 5.0
        assert clip.size == (1920, 1080)
        assert len(clip.clips) == len(script["scenes"][0]["elements"]) + 2
    finally:
        clip.close()


def test_static_caption_uses_verbatim_scene_narration_and_merged_style() -> None:
    """A scene caption uses narration_text and overrides only supplied style fields."""
    script = _script("example_script_extended.json")
    scene = script["scenes"][3]
    assert caption_text_for_scene(scene) == scene["narration_text"]
    style = resolve_caption_style(script, scene)
    assert style["font_size"] == 76
    assert style["color"] == script["project"]["caption_style"]["color"]
    clip = build_static_scene_clip(script, scene, {"duration_sec": 5.0}, ASSETS)
    try:
        caption = next(layer for layer in clip.clips if hasattr(layer, "text"))
        assert " ".join(caption.text.split()) == scene["narration_text"]
    finally:
        clip.close()


def test_full_video_concatenates_all_manifest_scenes_in_order() -> None:
    """The full clip duration equals the sum of all scene durations."""
    script = _script("example_script.json")
    manifest = json.loads(
        (ROOT / "projects/understanding_gpu_architecture/build_manifest.json").read_text(
            encoding="utf-8"
        )
    )
    manifest["scenes"] = [
        {
            "id": scene["id"],
            "start_time_sec": index * 2.0,
            "end_time_sec": (index + 1) * 2.0,
            "duration_sec": 2.0,
        }
        for index, scene in enumerate(manifest["scenes"])
    ]
    clip = build_full_video_clip(script, manifest, ASSETS, ROOT / "projects/understanding_gpu_architecture")
    try:
        expected = sum(float(scene["duration_sec"]) for scene in manifest["scenes"])
        expected += sum(
            float(scene.get("pause_before_sec", 0.0))
            for scene in script["scenes"][1:]
        )
        assert abs(clip.duration - expected) <= 0.01
        assert clip.size == tuple(script["project"]["resolution"])
    finally:
        clip.close()
