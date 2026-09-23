"""Tests that MoviePy element frames follow the pure keyframe resolver."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from creatortainment.render.keyframes import resolve_element_state
from creatortainment.render.moviepy_scene import build_static_scene_clip
from creatortainment.timeline import timed_element


ROOT = Path(__file__).parents[1]
ASSETS = ROOT / "assets"
PROJECT = ROOT / "projects/understanding_gpu_architecture"


def _script() -> dict:
    """Load the real portrait example script."""
    return json.loads(
        (ROOT / "scripts/testing_scripts/example_script.json").read_text(
            encoding="utf-8"
        )
    )


def _manifest() -> dict:
    """Load the aligned manifest for the real portrait example."""
    return json.loads(
        (PROJECT / "build_manifests/example_script.json").read_text(
            encoding="utf-8"
        )
    )


def _alpha_bounds(mask: np.ndarray) -> tuple[int, int, int, int] | None:
    """Return the non-transparent pixel bounds of a rendered element."""
    ys, xs = np.where(mask > 0.01)
    if len(xs) == 0:
        return None
    return int(xs.min()), int(ys.min()), int(xs.max() + 1), int(ys.max() + 1)


def test_scene_three_character_frames_follow_resolved_state() -> None:
    """Animated character frames use resolver opacity, position, and size."""
    script = _script()
    manifest = _manifest()
    scene = script["scenes"][2]
    scene_manifest = manifest["scenes"][2]
    element = next(item for item in scene["elements"] if item["id"] == "main_character")
    timed = timed_element(element, scene, scene_manifest, manifest)
    first, second = timed["keyframes"]
    clip = build_static_scene_clip(
        script, scene, scene_manifest, ASSETS, manifest
    )
    element_layer = clip.clips[2]
    try:
        before = element_layer.mask.get_frame(0.0)
        after_local = second["time_sec"] - scene_manifest["start_time_sec"] + 0.01
        after = element_layer.mask.get_frame(after_local)
        assert float(before.max()) == 0.0
        bounds = _alpha_bounds(after)
        assert bounds is not None
        state = resolve_element_state(timed, second["time_sec"] + 0.01)
        expected_height = round(state["size_value"] * script["project"]["resolution"][1])
        assert abs(after.shape[0] - expected_height) <= 2
        expected_position = (
            round(state["pos"][0] - after.shape[1] / 2),
            round(state["pos"][1] - after.shape[0]),
        )
        assert element_layer.pos(after_local) == expected_position
    finally:
        clip.close()


@pytest.mark.parametrize("anchor", ["top_left", "center", "bottom_center"])
def test_dynamic_anchor_position_matches_resolved_state(anchor: str) -> None:
    """Dynamic clips place each anchor at the resolver's pixel coordinates."""
    script = _script()
    manifest = _manifest()
    scene = script["scenes"][2]
    scene_manifest = manifest["scenes"][2]
    original = next(item for item in scene["elements"] if item["id"] == "main_character")
    element = json.loads(json.dumps(original))
    element["anchor"] = anchor
    timed = timed_element(element, scene, scene_manifest, manifest)
    state = resolve_element_state(timed, timed["keyframes"][-1]["time_sec"] + 0.1)
    test_scene = json.loads(json.dumps(scene))
    test_scene["elements"] = [element]
    clip = build_static_scene_clip(
        script, test_scene, scene_manifest, ASSETS, manifest
    )
    layer = clip.clips[1]
    try:
        sample_time = clip.duration - 0.1
        frame = layer.get_frame(sample_time)
        width, height = frame.shape[1], frame.shape[0]
        expected = {
            "top_left": (round(state["pos"][0]), round(state["pos"][1])),
            "center": (
                round(state["pos"][0] - width / 2),
                round(state["pos"][1] - height / 2),
            ),
            "bottom_center": (
                round(state["pos"][0] - width / 2),
                round(state["pos"][1] - height),
            ),
        }[anchor]
        actual = layer.pos(sample_time)
        assert actual == expected
    finally:
        clip.close()


def test_static_element_anchor_regression() -> None:
    """A static first-keyframe element keeps its Phase 5 anchor placement."""
    script = _script()
    manifest = _manifest()
    scene = script["scenes"][0]
    scene_manifest = manifest["scenes"][0]
    element = next(item for item in scene["elements"] if item["id"] == "main_character")
    test_scene = json.loads(json.dumps(scene))
    test_scene["elements"] = [element]
    clip = build_static_scene_clip(
        script, test_scene, scene_manifest, ASSETS
    )
    layer = clip.clips[1]
    try:
        keyframe = element["keyframes"][0]
        assert layer.pos(0) == (round(keyframe["pos"][0] - layer.w / 2), round(keyframe["pos"][1] - layer.h))
    finally:
        clip.close()


def test_animated_size_matches_resolver_dimensions() -> None:
    """Animated element dimensions follow the resolved target size."""
    script = _script()
    manifest = _manifest()
    scene = script["scenes"][2]
    scene_manifest = manifest["scenes"][2]
    element = next(item for item in scene["elements"] if item["id"] == "core_grid")
    timed = timed_element(element, scene, scene_manifest, manifest)
    state = resolve_element_state(timed, timed["keyframes"][1]["time_sec"] + 0.1)
    clip = build_static_scene_clip(script, scene, scene_manifest, ASSETS, manifest)
    layer = clip.clips[1]
    try:
        expected_width = round(state["size_value"] * script["project"]["resolution"][0])
        sample_time = timed["keyframes"][1]["time_sec"] - scene_manifest["start_time_sec"] + 0.1
        assert abs(layer.get_frame(sample_time).shape[1] - expected_width) <= 1
    finally:
        clip.close()
