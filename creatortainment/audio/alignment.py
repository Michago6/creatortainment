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
    result: list[SceneAlignment] = []
    global_offset = 0
    for scene_number, scene in enumerate(scenes):
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
        start = float(scene_timestamps[0]["start"])
        end = float(scene_timestamps[-1]["end"])
        result.append(
            SceneAlignment(
                id=str(scene["id"]),
                word_offset=global_offset,
                word_count=word_count,
                start_time_sec=start,
                end_time_sec=end,
                duration_sec=end - start,
            )
        )
        global_offset = end_offset
    if global_offset != len(word_timestamps):
        raise ValueError(
            f"Alignment contains {len(word_timestamps) - global_offset} unused word timestamps."
        )
    return result
