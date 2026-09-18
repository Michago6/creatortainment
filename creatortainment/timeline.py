"""Resolve word-indexed scene cues to absolute narration times."""

from __future__ import annotations

from copy import deepcopy
from typing import Any


def trigger_time_sec(
    scene: dict[str, Any],
    scene_manifest: dict[str, Any],
    manifest: dict[str, Any],
    trigger_word_index: int,
) -> float:
    """Return the global start time for a scene-local word index."""
    word_count = scene_manifest.get("word_count")
    if not isinstance(word_count, int):
        raise ValueError("Scene manifest word_count must be an integer.")
    if not isinstance(trigger_word_index, int) or isinstance(trigger_word_index, bool):
        raise ValueError("trigger_word_index must be an integer.")
    if trigger_word_index < 0 or trigger_word_index >= word_count:
        raise ValueError(
            f"trigger_word_index {trigger_word_index} is outside scene "
            f"{scene.get('id', '<unnamed>')!r} word range 0..{word_count - 1}."
        )

    word_offset = scene_manifest.get("word_offset")
    timestamps = manifest.get("word_timestamps")
    if not isinstance(word_offset, int) or not isinstance(timestamps, list):
        raise ValueError("Manifest must contain integer word_offset and word_timestamps.")
    global_index = word_offset + trigger_word_index
    if global_index < 0 or global_index >= len(timestamps):
        raise ValueError(
            f"Resolved global word index {global_index} is outside word_timestamps."
        )
    timestamp = timestamps[global_index]
    if not isinstance(timestamp, dict) or not isinstance(timestamp.get("start"), (int, float)):
        raise ValueError(f"word_timestamps[{global_index}] has no numeric start time.")
    return float(timestamp["start"])


def timed_element(
    element: dict[str, Any],
    scene: dict[str, Any],
    scene_manifest: dict[str, Any],
    manifest: dict[str, Any],
) -> dict[str, Any]:
    """Return an element copy whose keyframes contain absolute time_sec values."""
    result = deepcopy(element)
    for keyframe in result.get("keyframes", []):
        if "trigger_word_index" not in keyframe:
            raise ValueError("Every element keyframe requires trigger_word_index.")
        keyframe["time_sec"] = trigger_time_sec(
            scene,
            scene_manifest,
            manifest,
            keyframe["trigger_word_index"],
        )
    return result
