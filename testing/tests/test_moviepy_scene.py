"""Tests static MoviePy scene composition at manifest duration and script resolution."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import numpy as np
import pytest
from moviepy import ColorClip, CompositeVideoClip

from creatortainment.render.moviepy_scene import (
    build_animated_caption_clip,
    build_full_video_clip,
    build_static_scene_clip,
    caption_text_for_scene,
    resolve_caption_style,
)
from creatortainment.render.timeline import build_scene_final_offsets


ROOT = Path(__file__).parents[2]
ASSETS = ROOT / "testing/assets"


def _script(name: str) -> dict:
    return json.loads(
        (ROOT / "testing/scripts" / name).read_text(encoding="utf-8")
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


def test_caption_text_excludes_audio_tags() -> None:
    assert caption_text_for_scene(
        {"narration_text": "[whispers] Hello [beat] there."}
    ) == "Hello there."


def test_extra_duration_keeps_scene_visuals_and_final_caption_active() -> None:
    script = _script("example_script.json")
    script = deepcopy(script)
    scene = script["scenes"][0]
    scene["extra_duration_sec"] = 1.5
    scene_manifest = {
        "start_time_sec": 0.0,
        "end_time_sec": 2.0,
        "duration_sec": 2.0,
        "word_offset": 0,
        "word_count": len(scene["narration_text"].split()),
    }
    manifest = {
        "word_timestamps": [
            {"start": float(index) * 0.5, "end": float(index + 1) * 0.5}
            for index in range(scene_manifest["word_count"])
        ]
    }
    clip = build_static_scene_clip(
        script,
        scene,
        scene_manifest,
        ASSETS,
        manifest,
    )
    try:
        assert clip.duration == pytest.approx(3.5)
        assert all(layer.duration == pytest.approx(3.5) for layer in clip.clips)
        caption = clip.clips[-1]
        assert caption.get_frame(3.49).shape[0] > 1
    finally:
        clip.close()


@pytest.mark.parametrize("rotation", [0, 30, -30])
def test_element_rotation_changes_rendered_asset_bounds(rotation: float) -> None:
    script = _script("example_script.json")
    script = deepcopy(script)
    element = next(
        item for item in script["scenes"][0]["elements"] if item["id"] == "main_character"
    )
    element["rotation"] = rotation
    clip = build_static_scene_clip(
        script,
        script["scenes"][0],
        {"duration_sec": 2.0},
        ASSETS,
    )
    try:
        element_layer = clip.clips[2]
        if rotation == 0:
            assert element_layer.w > 0.0
            assert element_layer.h == pytest.approx(0.32 * 1920, abs=2)
        else:
            assert element_layer.w > 0.0
            assert element_layer.h > 0.32 * 1920
        frame = element_layer.get_frame(0.5)
        assert np.asarray(frame).max() > 0
    finally:
        clip.close()


def test_full_video_concatenates_all_manifest_scenes_in_order() -> None:
    """The full clip duration equals the sum of all scene durations."""
    script = _script("example_script.json")
    manifest = json.loads(
        (ROOT / "projects/understanding_gpu_architecture/build_manifests/example_script.json").read_text(
            encoding="utf-8"
        )
    )
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


def test_preview_scene_numbers_are_fixed_top_right_overlays() -> None:
    script = _script("example_script.json")
    manifest = json.loads(
        (
            ROOT
            / "projects/understanding_gpu_architecture/build_manifests/example_script.json"
        ).read_text(encoding="utf-8")
    )
    preview_script = deepcopy(script)
    preview_script["project"]["resolution"] = [270, 480]
    clip = build_full_video_clip(
        preview_script,
        manifest,
        ASSETS,
        ROOT / "projects/understanding_gpu_architecture",
        show_scene_numbers=True,
    )
    normal = build_full_video_clip(
        preview_script,
        manifest,
        ASSETS,
        ROOT / "projects/understanding_gpu_architecture",
    )
    try:
        overlays = [
            layer for layer in clip.clips
            if getattr(layer, "text", None) in {"1", "2", "3"}
        ]
        assert [layer.text for layer in overlays] == ["1", "2", "3"]
        offsets = build_scene_final_offsets(preview_script, manifest)
        assert [layer.start for layer in overlays] == pytest.approx(
            [offset.final_start_sec for offset in offsets]
        )
        assert all(
            layer.pos(0) == layer.pos(min(0.1, layer.duration / 2))
            for layer in overlays
        )
        assert all(layer.pos(0)[0] + layer.w <= 270 for layer in overlays)
        assert all(layer.pos(0)[1] >= 0 for layer in overlays)
        assert len(normal.clips) == len(preview_script["scenes"])
    finally:
        clip.close()
        normal.close()


def test_full_video_inherits_backgrounds_across_scenes() -> None:
    script = deepcopy(_script("example_script.json"))
    inherited = script["scenes"][0]["bg"]
    for scene in script["scenes"][1:]:
        scene.pop("bg", None)
    manifest = json.loads(
        (
            ROOT
            / "projects/understanding_gpu_architecture/build_manifests/example_script.json"
        ).read_text(encoding="utf-8")
    )

    clip = build_full_video_clip(
        script,
        manifest,
        ASSETS,
        ROOT / "projects/understanding_gpu_architecture",
    )
    try:
        assert clip.duration > 0
        assert all(scene.get("bg") in {inherited, None} for scene in script["scenes"])
    finally:
        clip.close()


def test_animated_caption_is_blank_then_advances_and_holds_final_word() -> None:
    """Aligned scene captions are transparent before speech and cache active states."""
    script = _script("example_script.json")
    manifest = json.loads(
        (ROOT / "projects/understanding_gpu_architecture/build_manifests/example_script.json").read_text(
            encoding="utf-8"
        )
    )
    manifest = deepcopy(manifest)
    scene_manifest = manifest["scenes"][0]
    for timestamp in manifest["word_timestamps"][: scene_manifest["word_count"]]:
        timestamp["start"] += 0.5
        timestamp["end"] += 0.5
    scene_manifest["end_time_sec"] += 0.5
    scene_manifest["duration_sec"] += 0.5
    scene = script["scenes"][0]
    caption = build_animated_caption_clip(
        script,
        scene,
        scene_manifest,
        manifest,
        tuple(script["project"]["resolution"]),
        float(scene_manifest["duration_sec"]),
    )
    try:
        assert caption.mask.get_frame(0.0).max() == 0.0
        first_word_time = float(manifest["word_timestamps"][0]["start"])
        first = caption.get_frame(first_word_time - scene_manifest["start_time_sec"])
        assert first.shape[0] > 1
        assert caption.caption_image_cache.render_count == 1
        caption.get_frame(first_word_time - scene_manifest["start_time_sec"] + 0.01)
        assert caption.caption_image_cache.hit_count >= 1
        last_word = manifest["word_timestamps"][scene_manifest["word_offset"] + scene_manifest["word_count"] - 1]
        held = caption.get_frame(float(last_word["end"]) - scene_manifest["start_time_sec"] + 0.5)
        assert held.shape[0] > 1
        assert caption.caption_image_cache.render_count >= 2
    finally:
        caption.close()


@pytest.mark.parametrize("transition", [0.1, 0.2, 0.3])
def test_transition_delays_caption_to_logical_scene_start(transition: float) -> None:
    """Incoming visual overlap does not move an animated caption before narration."""
    script = _script("example_script.json")
    script = deepcopy(script)
    script["scenes"][1]["transition_in"] = {
        "type": "crossfade",
        "duration_sec": transition,
    }
    script["scenes"][1]["pause_before_sec"] = 0.0
    scene = script["scenes"][1]
    scene["narration_text"] = "second"
    scene["elements"] = []
    scene_manifest = {
        "start_time_sec": 1.0,
        "end_time_sec": 2.0,
        "duration_sec": 1.0,
        "word_offset": 0,
        "word_count": 1,
    }
    manifest = {
        "word_timestamps": [{"word": scene["narration_text"].split()[0], "start": 1.0, "end": 2.0}],
    }
    offsets = build_scene_final_offsets(
        {"scenes": [script["scenes"][0], scene]},
        {"scenes": [{"duration_sec": 1.0}, scene_manifest]},
    )
    clip = build_static_scene_clip(
        script,
        scene,
        scene_manifest,
        ASSETS,
        manifest,
        caption_start_offset_sec=transition,
    )
    try:
        caption = clip.clips[-1]
        assert offsets[1].visual_start_sec + caption.start == pytest.approx(
            offsets[1].final_start_sec
        )
        assert caption.get_frame(0.0).shape[0] > 1
    finally:
        clip.close()


def test_transition_caption_delay_preserves_pause_timing() -> None:
    """A pause still places the caption at the narration start after a transition."""
    script = _script("example_script.json")
    script = deepcopy(script)
    transition = 0.2
    pause = 0.4
    script["scenes"][1]["transition_in"] = {
        "type": "crossfade",
        "duration_sec": transition,
    }
    script["scenes"][1]["pause_before_sec"] = pause
    scene = script["scenes"][1]
    scene["narration_text"] = "second"
    scene["elements"] = []
    scene_manifest = {
        "start_time_sec": 1.0,
        "end_time_sec": 2.0,
        "duration_sec": 1.0,
        "word_offset": 0,
        "word_count": 1,
    }
    manifest = {
        "word_timestamps": [{"word": scene["narration_text"].split()[0], "start": 1.0, "end": 2.0}],
    }
    offsets = build_scene_final_offsets(
        {"scenes": [script["scenes"][0], scene]},
        {"scenes": [{"duration_sec": 1.0}, scene_manifest]},
    )
    clip = build_static_scene_clip(
        script,
        scene,
        scene_manifest,
        ASSETS,
        manifest,
        caption_start_offset_sec=transition,
    )
    try:
        caption = clip.clips[-1]
        assert offsets[1].visual_start_sec + pause + caption.start == pytest.approx(
            offsets[1].narration_start_sec
        )
    finally:
        clip.close()


def test_hard_cut_caption_starts_at_existing_scene_start() -> None:
    """Without an incoming transition, captions retain their existing timing."""
    script = _script("example_script.json")
    scene = script["scenes"][1]
    scene["narration_text"] = "second"
    scene["elements"] = []
    scene_manifest = {
        "start_time_sec": 1.0,
        "end_time_sec": 2.0,
        "duration_sec": 1.0,
        "word_offset": 0,
        "word_count": 1,
    }
    manifest = {
        "word_timestamps": [{"word": scene["narration_text"].split()[0], "start": 1.0, "end": 2.0}],
    }
    clip = build_static_scene_clip(script, scene, scene_manifest, ASSETS, manifest)
    try:
        assert clip.clips[-1].start == pytest.approx(0.0)
    finally:
        clip.close()


def test_animated_caption_transparent_padding_preserves_background() -> None:
    script = _script("example_script.json")
    scene = script["scenes"][0]
    scene["narration_text"] = "hello world"
    scene_manifest = {
        "start_time_sec": 0.0,
        "word_offset": 0,
    }
    manifest = {
        "word_timestamps": [
            {"start": 0.0, "end": 1.0},
            {"start": 1.0, "end": 2.0},
        ]
    }
    caption = build_animated_caption_clip(
        script,
        scene,
        scene_manifest,
        manifest,
        (1080, 1920),
        2.0,
    )
    background = ColorClip((1080, 1920), color=(100, 150, 200), duration=2.0)
    composite = CompositeVideoClip([background, caption], size=(1080, 1920))
    try:
        rendered = caption.get_frame(0.1)
        alpha = caption.mask.get_frame(0.1)
        frame = composite.get_frame(0.1)
        assert alpha[0, 0] == 0.0
        assert tuple(frame[int(caption.pos(0.1)[1]), int(caption.pos(0.1)[0])]) == (
            100,
            150,
            200,
        )
        assert np.max(rendered) == 255
    finally:
        composite.close()
        background.close()
        caption.close()
