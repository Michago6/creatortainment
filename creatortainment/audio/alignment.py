"""Slice global narration alignment data into scene ranges."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Iterable

from .tokenize import tokenize


@dataclass(frozen=True)
class SceneAlignment:
    id: str
    word_offset: int
    word_count: int
    start_time_sec: float
    end_time_sec: float
    duration_sec: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def align_scenes(
    scenes: Iterable[dict[str, Any]],
    word_timestamps: list[dict[str, Any]],
    *,
    pause_default_sec: float = 0.3,
) -> list[SceneAlignment]:
    scene_list = list(scenes)
    scene_ranges: list[tuple[dict[str, Any], int, list[dict[str, Any]]]] = []
    global_offset = 0
    for scene_number, scene in enumerate(scene_list):
        words = tokenize(scene["narration_text"])
        word_count = len(words)
        end_offset = global_offset + word_count
        if end_offset > len(word_timestamps):
            raise ValueError(
                f"Alignment has {len(word_timestamps)} words but scene "
                f"{scene.get('id', scene_number)!r} requires index {end_offset - 1}."
            )
        if word_count == 0:
            raise ValueError(f"Scene {scene.get('id', scene_number)!r} has no narration words.")
        scene_timestamps = word_timestamps[global_offset:end_offset]
        scene_ranges.append((scene, global_offset, scene_timestamps))
        global_offset = end_offset
    if global_offset != len(word_timestamps):
        raise ValueError(
            f"Alignment contains {len(word_timestamps) - global_offset} unused word timestamps."
        )

    result: list[SceneAlignment] = []
    for index, (scene, word_offset, scene_timestamps) in enumerate(scene_ranges):
        start = float(scene_timestamps[0]["start"])
        final_word_end = float(scene_timestamps[-1]["end"])
        if index + 1 < len(scene_ranges):
            next_start = float(scene_ranges[index + 1][2][0]["start"])
            if next_start < final_word_end:
                raise ValueError(
                    f"Alignment overlaps scenes {scene.get('id', index)!r} and "
                    f"{scene_ranges[index + 1][0].get('id', index + 1)!r}: "
                    f"next scene starts at {next_start:.3f}s before the current "
                    f"scene ends at {final_word_end:.3f}s."
                )
            end = next_start
        else:
            end = final_word_end
        result.append(
            SceneAlignment(
                id=str(scene["id"]),
                word_offset=word_offset,
                word_count=len(scene_timestamps),
                start_time_sec=start,
                end_time_sec=end,
                duration_sec=end - start,
            )
        )
    return result
