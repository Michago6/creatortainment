"""Tests shared conversion of scene-local word triggers to global start times."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from creatortainment.timeline import trigger_time_sec, timed_element


ROOT = Path(__file__).parents[2]


def _script() -> dict:
    """Load the real portrait example script."""
    return json.loads(
        (ROOT / "testing/scripts/example_script.json").read_text(
            encoding="utf-8"
        )
    )


def _manifest() -> dict:
    """Load the real project alignment fixture."""
    return json.loads(
        (ROOT / "projects/understanding_gpu_architecture/build_manifests/example_script.json").read_text(
            encoding="utf-8"
        )
    )


def test_trigger_zero_resolves_to_scene_start() -> None:
    """The first local trigger resolves to the scene's first word start."""
    script = _script()
    manifest = _manifest()
    scene = script["scenes"][1]
    scene_manifest = manifest["scenes"][1]
    assert trigger_time_sec(scene, scene_manifest, manifest, 0) == scene_manifest["start_time_sec"]


def test_trigger_mid_scene_uses_global_word_start() -> None:
    """A middle trigger uses word_offset plus local index and the word start."""
    script = _script()
    manifest = _manifest()
    scene_manifest = manifest["scenes"][1]
    index = 3
    global_index = scene_manifest["word_offset"] + index
    assert trigger_time_sec(
        script["scenes"][1], scene_manifest, manifest, index
    ) == manifest["word_timestamps"][global_index]["start"]


def test_trigger_last_scene_word_resolves() -> None:
    """The final valid local trigger resolves without an off-by-one error."""
    script = _script()
    manifest = _manifest()
    scene = script["scenes"][2]
    scene_manifest = manifest["scenes"][2]
    index = scene_manifest["word_count"] - 1
    global_index = scene_manifest["word_offset"] + index
    assert trigger_time_sec(scene, scene_manifest, manifest, index) == manifest["word_timestamps"][global_index]["start"]


def test_trigger_out_of_range_raises() -> None:
    """An index beyond the scene word range raises a clear error."""
    script = _script()
    manifest = _manifest()
    with pytest.raises(ValueError, match="outside scene"):
        trigger_time_sec(script["scenes"][0], manifest["scenes"][0], manifest, 16)


def test_element_keyframes_receive_absolute_times() -> None:
    """Element keyframes use the shared resolver for their absolute times."""
    script = _script()
    manifest = _manifest()
    element = script["scenes"][0]["elements"][1]
    timed = timed_element(element, script["scenes"][0], manifest["scenes"][0], manifest)
    assert timed["keyframes"][0]["time_sec"] == manifest["word_timestamps"][6]["start"]
