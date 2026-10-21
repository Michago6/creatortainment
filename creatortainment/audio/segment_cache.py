"""Persistent cache helpers for independently generated narration segments."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .elevenlabs_client import NarrationSegmentResult, WordTimestamp
from ..schema.models import NarrationSegment
from .tokenize import spoken_words


def narration_segment_hash(
    segment: NarrationSegment,
    model: str,
    speed: float = 1.0,
) -> str:
    value = json.dumps(
        {
            "text": segment.text,
            "voice_id": segment.voice_id,
            "model": model,
            "speed": speed,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def find_cached_segment(
    narrations_dir: Path,
    segment: NarrationSegment,
    model: str,
    speed: float = 1.0,
) -> NarrationSegmentResult | None:
    cache_key = narration_segment_hash(segment, model, speed)
    sidecar_path = narrations_dir / f"segment_{cache_key}.json"
    audio_path = narrations_dir / f"segment_{cache_key}.mp3"
    if not sidecar_path.is_file() or not audio_path.is_file():
        return None
    try:
        value = json.loads(sidecar_path.read_text(encoding="utf-8"))
        timestamps = value["word_timestamps"]
        if not isinstance(timestamps, list):
            return None
        expected_words = spoken_words(segment.text)
        if len(timestamps) != len(expected_words):
            return None
        words = [
            WordTimestamp(
                word=item["word"],
                start=float(item["start"]),
                end=float(item["end"]),
                segment_id=segment.id,
                scene_id=segment.scene_id,
                voice_id=segment.voice_id,
                segment_word_index=index,
            )
            for index, item in enumerate(timestamps)
        ]
        if [item.word for item in words] != expected_words:
            return None
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None
    return NarrationSegmentResult(segment, audio_path.read_bytes(), words)


def write_cached_segment(
    narrations_dir: Path,
    result: NarrationSegmentResult,
    model: str,
    speed: float = 1.0,
) -> tuple[Path, Path]:
    narrations_dir.mkdir(parents=True, exist_ok=True)
    cache_key = narration_segment_hash(result.segment, model, speed)
    audio_path = narrations_dir / f"segment_{cache_key}.mp3"
    sidecar_path = narrations_dir / f"segment_{cache_key}.json"
    audio_path.write_bytes(result.audio_bytes)
    sidecar = {
        "segment_id": result.segment.id,
        "scene_id": result.segment.scene_id,
        "text": result.segment.text,
        "voice_id": result.segment.voice_id,
        "tts_model": model,
        "speed": speed,
        "word_timestamps": [
            WordTimestamp(
                word=timestamp.word,
                start=timestamp.start,
                end=timestamp.end,
            ).to_dict()
            for timestamp in result.word_timestamps
        ],
    }
    sidecar_path.write_text(
        json.dumps(sidecar, indent=2) + "\n",
        encoding="utf-8",
    )
    return audio_path, sidecar_path


def cached_segment_paths(
    narrations_dir: Path,
    segment: NarrationSegment,
    model: str,
    speed: float = 1.0,
) -> tuple[Path, Path]:
    cache_key = narration_segment_hash(segment, model, speed)
    return (
        narrations_dir / f"segment_{cache_key}.mp3",
        narrations_dir / f"segment_{cache_key}.json",
    )
