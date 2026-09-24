"""Final-video scene offsets shared by video and audio assembly."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..timeline import trigger_time_sec

@dataclass(frozen=True)
class SceneOffset:
    """Placement of one scene's narration clip in the final video."""

    scene_index: int
    pause_before_sec: float
    final_start_sec: float
    narration_start_sec: float
    narration_end_sec: float
    transition_duration_sec: float = 0.0
    unit_duration_sec: float = 0.0


def scene_duration_sec(
    scene: dict[str, Any],
    scene_manifest: dict[str, Any],
) -> float:
    """Return narration duration plus an optional authored visual hold."""
    narration_duration = float(scene_manifest["duration_sec"])
    extra_duration = float(scene.get("extra_duration_sec", 0.0))
    if narration_duration <= 0.0:
        raise ValueError(f"Scene {scene.get('id', '<unnamed>')!r} has invalid duration.")
    if extra_duration < 0.0:
        raise ValueError(
            f"Scene {scene.get('id', '<unnamed>')!r} has invalid extra duration."
        )
    return narration_duration + extra_duration


def build_scene_final_offsets(
    script: dict[str, Any],
    manifest: dict[str, Any],
) -> list[SceneOffset]:
    """Compute final-video placement including pauses and transition overlaps."""
    scenes = script.get("scenes", [])
    scene_manifests = manifest.get("scenes", [])
    if len(scenes) != len(scene_manifests):
        raise ValueError("Script and manifest scene counts must match.")
    offsets: list[SceneOffset] = []
    cursor = 0.0
    for index, (scene, scene_manifest) in enumerate(zip(scenes, scene_manifests)):
        pause = float(scene.get("pause_before_sec", 0.0)) if index > 0 else 0.0
        if pause < 0.0:
            raise ValueError(f"Scene {scene.get('id', index)!r} has an invalid pause.")
        narration_duration = float(scene_manifest["duration_sec"])
        scene_duration = scene_duration_sec(scene, scene_manifest)
        transition = 0.0
        if index > 0:
            transition_value = scene.get("transition_in")
            if transition_value is not None:
                transition = float(transition_value["duration_sec"])
                if transition <= 0.0:
                    raise ValueError(
                        f"Scene {scene.get('id', index)!r} has an invalid transition duration."
                    )
                if transition > cursor:
                    raise ValueError(
                        f"Scene {scene.get('id', index)!r} transition exceeds the "
                        "available preceding timeline."
                    )
        unit_duration = pause + scene_duration
        scene_start = cursor - transition
        narration_start = scene_start + pause
        offsets.append(
            SceneOffset(
                scene_index=index,
                pause_before_sec=pause,
                final_start_sec=scene_start,
                narration_start_sec=narration_start,
                narration_end_sec=narration_start + narration_duration,
                transition_duration_sec=transition,
                unit_duration_sec=unit_duration,
            )
        )
        cursor = scene_start + unit_duration
    return offsets


def resolve_cue_to_final_video_time(
    scene: dict[str, Any],
    trigger_word_index: int,
    manifest: dict[str, Any],
    scene_offsets: list[SceneOffset],
) -> float:
    """Map a raw-narration cue to its absolute final-video timestamp."""
    scene_manifests = manifest.get("scenes", [])
    if not isinstance(scene_manifests, list):
        raise ValueError("Manifest scenes must be a list.")
    scene_id = scene.get("id")
    matching_indexes = [
        index
        for index, scene_manifest in enumerate(scene_manifests)
        if isinstance(scene_manifest, dict)
        and scene_manifest.get("id", scene_id) == scene_id
    ]
    if len(matching_indexes) != 1:
        raise ValueError(f"Could not uniquely locate scene {scene_id!r} in the manifest.")
    scene_index = matching_indexes[0]
    if scene_index >= len(scene_offsets):
        raise ValueError(f"No final-video offset exists for scene {scene_id!r}.")
    scene_manifest = scene_manifests[scene_index]
    offset = scene_offsets[scene_index]
    raw_trigger_time = trigger_time_sec(
        scene,
        scene_manifest,
        manifest,
        trigger_word_index,
    )
    return (
        offset.narration_start_sec
        + raw_trigger_time
        - float(scene_manifest["start_time_sec"])
    )
