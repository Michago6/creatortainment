"""Tests that MoviePy element frames follow the pure keyframe resolver."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from creatortainment.render.keyframes import resolve_element_state
from creatortainment.render.moviepy_scene import build_static_scene_clip
from creatortainment.timeline import timed_element


ROOT = Path(__file__).parents[1]
ASSETS = ROOT / "assets"
PROJECT = ROOT / "projects/understanding_gpu_architecture"


def _script() -> dict:
    """Load the real portrait example script."""
    return json.loads(
        (ROOT / "scripts/example_scripts/example_script.json").read_text(
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
        assert _alpha_bounds(before) is None
        bounds = _alpha_bounds(after)
        assert bounds is not None
        state = resolve_element_state(timed, second["time_sec"] + 0.01)
        expected_height = round(state["size_value"] * script["project"]["resolution"][1])
        assert abs((bounds[3] - bounds[1]) - expected_height) <= 2
        center_x = (bounds[0] + bounds[2]) / 2
        assert abs(center_x - state["pos"][0]) <= 2
    finally:
        clip.close()
