"""Build manifest persistence and narration cache handling."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any

from .alignment import align_scenes
from ..schema.models import NarrationSegment
from .elevenlabs_client import (
    NarrationClient,
    NarrationResult,
    NarrationSegmentResult,
    narration_text_and_pauses,
)
from .tokenize import spoken_words

DEFAULT_TTS_MODEL = "eleven_flash_v2_5"
AUDIO_DURATION_TOLERANCE_SEC = 0.1
DEFAULT_TTS_SPEED = 1.0


def narration_hash(script: dict[str, Any]) -> str:
    speed = _project_value(script, "speed", DEFAULT_TTS_SPEED)
    normalized = _normalized_segments(script)
    if normalized is not None and _has_segment_syntax(script):
        model = _project_value(script, "tts_model", DEFAULT_TTS_MODEL)
        value = json.dumps(
            [
                {"text": segment.text, "voice_id": segment.voice_id}
                for segment in normalized
            ],
            separators=(",", ":"),
        )
        return narration_hash_for_text(value, model, speed)
    text, _ = narration_text_and_pauses(script["scenes"])
    model = script.get("project", {}).get("tts_model", DEFAULT_TTS_MODEL)
    return narration_hash_for_text(text, model, speed)


def narration_hash_for_text(
    text: str, model: str = DEFAULT_TTS_MODEL, speed: float = DEFAULT_TTS_SPEED
) -> str:
    """Return the cache hash used for narration sidecar text and model."""
    return hashlib.sha256(f"{text}\n{model}\n{speed:.12g}".encode("utf-8")).hexdigest()


def validate_audio_timing(audio_duration: float, timestamp_end: float) -> None:
    difference = timestamp_end - audio_duration
    if difference > AUDIO_DURATION_TOLERANCE_SEC:
        raise ValueError(
            "Cached narration audio is shorter than its word timestamps: "
            f"audio={audio_duration:.3f}s, timestamps={timestamp_end:.3f}s, "
            f"difference={difference:.3f}s. "
            "Run align with --force-audio to refresh narration."
        )


def cached_words_match(text: str, timestamps: Any) -> bool:
    expected = spoken_words(text)
    return (
        isinstance(timestamps, list)
        and len(timestamps) == len(expected)
        and [item.get("word") for item in timestamps if isinstance(item, dict)]
        == expected
    )


def _project_value(script: Any, key: str, default: Any = None) -> Any:
    project = script["project"]
    return project.get(key, default) if isinstance(project, dict) else project.get(key, default)


def _has_segment_syntax(script: Any) -> bool:
    return any(
        (scene.get("narration_segments") is not None if isinstance(scene, dict)
         else scene.narration_segments is not None)
        for scene in script["scenes"]
    )


def _normalized_segments(script: Any) -> list[NarrationSegment] | None:
    method = getattr(script, "normalized_narration_segments", None)
    if method is not None:
        return method()
    if _has_segment_syntax(script):
        raise ValueError("Multi-voice scripts must be validated typed ScriptModel instances.")
    return None


def _scene_dicts_with_segment_text(script: Any) -> list[dict[str, Any]]:
    result = []
    for scene in script["scenes"]:
        if isinstance(scene, dict):
            scene_value = dict(scene)
            segments = scene_value.get("narration_segments")
            if segments is not None:
                scene_value["narration_text"] = " ".join(
                    item["text"] for item in segments
                )
            result.append(scene_value)
        else:
            scene_value = scene.model_dump(exclude_none=True)
            segment_models = scene.narration_segments
            if segment_models is not None:
                scene_value["narration_text"] = " ".join(
                    item.text for item in segment_models
                )
            result.append(scene_value)
    return result


def _segment_audio_duration(path: Path, fallback: float) -> float:
    import subprocess

    probe = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=nw=1:nk=1",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    try:
        duration = float(probe.stdout.strip())
    except ValueError:
        return fallback
    if not math.isfinite(duration) or duration <= 0.0:
        return fallback
    return duration


def audio_duration_sec(path: Path, fallback: float) -> float:
    return _segment_audio_duration(path, fallback)


def _segment_scene_alignments(
    script: Any,
    records: list[dict[str, Any]],
    flattened: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    segments = _normalized_segments(script)
    if segments is None:
        raise ValueError("Segment scene alignment requires normalized segments.")
    segment_by_id = {segment.id: segment for segment in segments}
    scene_values = _scene_dicts_with_segment_text(script)
    scene_ids = [str(scene["id"]) for scene in scene_values]
    scene_records = {scene_id: [] for scene_id in scene_ids}
    for record in records:
        segment_id = record.get("id")
        segment = segment_by_id.get(segment_id)
        if segment is None:
            raise ValueError("Cached multi-voice segment IDs do not match the script.")
        record["scene_id"] = segment.scene_id
        scene_records.setdefault(segment.scene_id, []).append(record)
    for timestamp in flattened:
        segment = segment_by_id.get(timestamp.get("segment_id"))
        if segment is None:
            raise ValueError("Cached multi-voice word timestamps do not match the script.")
        timestamp["scene_id"] = segment.scene_id
        timestamp["voice_id"] = segment.voice_id

    result: list[dict[str, Any]] = []
    word_offset = 0
    for scene_id in scene_ids:
        scene_segment_records = scene_records.get(scene_id, [])
        if not scene_segment_records:
            raise ValueError(f"Scene {scene_id!r} has no narration segments.")
        scene_words = [
            timestamp for timestamp in flattened if timestamp.get("scene_id") == scene_id
        ]
        start = min(float(record["start_sec"]) for record in scene_segment_records)
        end = max(float(record["end_sec"]) for record in scene_segment_records)
        result.append(
            {
                "id": scene_id,
                "word_offset": word_offset,
                "word_count": len(scene_words),
                "start_time_sec": start,
                "end_time_sec": end,
                "duration_sec": end - start,
            }
        )
        word_offset += len(scene_words)
    return result


def read_manifest(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValueError(f"Could not read manifest {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"Manifest {path} contains invalid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError("The build manifest must be a JSON object.")
    return value


def write_manifest(path: Path, manifest: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


def refresh_cached_manifest_scenes(
    script: dict[str, Any],
    manifest: dict[str, Any],
    project_dir: Path,
    *,
    validate_audio_duration: bool = True,
) -> bool:
    """Refresh scene segmentation while reusing validated narration data."""
    expected_hash = narration_hash(script)
    if manifest.get("narration_hash") != expected_hash:
        raise ValueError(
            "Cached narration does not match the script narration. "
            "Run align before rendering."
        )
    if _has_segment_syntax(script):
        return _refresh_cached_segment_manifest(script, manifest, project_dir)

    text, _ = narration_text_and_pauses(script["scenes"])
    expected_words = spoken_words(text)
    timestamps = manifest.get("word_timestamps")
    if not isinstance(timestamps, list) or len(timestamps) != len(expected_words):
        raise ValueError(
            "Cached narration word timestamps do not match the script narration. "
            "Run align before rendering."
        )
    previous_end = 0.0
    for index, (expected_word, timestamp) in enumerate(zip(expected_words, timestamps)):
        if not isinstance(timestamp, dict) or timestamp.get("word") != expected_word:
            raise ValueError(
                f"Cached narration word timestamp {index} does not match the script. "
                "Run align before rendering."
            )
        try:
            start = float(timestamp["start"])
            end = float(timestamp["end"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(
                f"Cached narration timestamp {index} is invalid. Run align before rendering."
            ) from exc
        if (
            not math.isfinite(start)
            or not math.isfinite(end)
            or start < previous_end
            or end < start
        ):
            raise ValueError(
                f"Cached narration timestamp {index} is invalid. Run align before rendering."
            )
        previous_end = end

    audio_value = manifest.get("narration_audio_path")
    if not isinstance(audio_value, str) or not audio_value:
        raise ValueError(
            "Cached narration audio path is invalid. Run align before rendering."
        )
    audio_path = Path(audio_value)
    if not audio_path.is_absolute():
        audio_path = project_dir / audio_path
    if not audio_path.is_file():
        raise FileNotFoundError(
            f"Cached narration audio file does not exist: {audio_path}"
        )
    audio_duration: float | None = None
    if validate_audio_duration:
        audio_duration = _segment_audio_duration(audio_path, previous_end)
        validate_audio_timing(audio_duration, previous_end)

    aligned_scenes = [
        scene.to_dict()
        for scene in align_scenes(
            script["scenes"],
            timestamps,
            narration_duration_sec=audio_duration,
        )
    ]
    changed = manifest.get("scenes") != aligned_scenes
    if changed:
        manifest["scenes"] = aligned_scenes
    return changed


def _refresh_cached_segment_manifest(
    script: Any,
    manifest: dict[str, Any],
    project_dir: Path,
) -> bool:
    segments = _normalized_segments(script)
    cached = manifest.get("narration_segments")
    if segments is None or not isinstance(cached, list) or len(cached) != len(segments):
        raise ValueError("Cached multi-voice narration segments do not match the script.")
    flattened = manifest.get("word_timestamps")
    if not isinstance(flattened, list):
        raise ValueError("Cached multi-voice narration has no word timestamps.")
    for expected, record in zip(segments, cached):
        if not isinstance(record, dict) or any(
            record.get(key) != value
            for key, value in (
                ("id", expected.id),
                ("voice_id", expected.voice_id),
                ("text", expected.text),
            )
        ):
            raise ValueError("Cached multi-voice narration segments do not match the script.")
        audio_value = record.get("audio_path")
        audio_path = Path(audio_value) if isinstance(audio_value, str) else Path()
        if not audio_path.is_absolute():
            audio_path = project_dir / audio_path
        if not audio_path.is_file():
            raise FileNotFoundError(f"Cached narration audio file does not exist: {audio_path}")
        record["scene_id"] = expected.scene_id
    segment_by_id = {segment.id: segment for segment in segments}
    for timestamp in flattened:
        segment_id = timestamp.get("segment_id") if isinstance(timestamp, dict) else None
        segment = segment_by_id.get(segment_id)
        if segment is None:
            raise ValueError("Cached multi-voice word timestamps do not match the script.")
        timestamp["scene_id"] = segment.scene_id
        timestamp["voice_id"] = segment.voice_id
    aligned = _segment_scene_alignments(script, cached, flattened)
    changed = manifest.get("scenes") != aligned
    if changed:
        manifest["scenes"] = aligned
    return changed


def build_segment_manifest(
    script: Any,
    manifest_path: Path,
    project_dir: Path,
    results: list[NarrationSegmentResult],
    audio_paths: list[Path],
    model: str,
    speed: float = DEFAULT_TTS_SPEED,
) -> dict[str, Any]:
    """Build a manifest from independently aligned sequential narration segments."""
    segments = _normalized_segments(script)
    if segments is None or len(results) != len(segments) or len(audio_paths) != len(segments):
        raise ValueError("Segment results do not match the script narration segments.")
    records: list[dict[str, Any]] = []
    flattened: list[dict[str, Any]] = []
    cursor = 0.0
    previous_scene_id: str | None = None
    scene_values = _scene_dicts_with_segment_text(script)
    scene_by_id = {str(scene["id"]): scene for scene in scene_values}
    base_records: list[tuple[NarrationSegment, NarrationSegmentResult, Path, float, float]] = []
    for segment, result, audio_path in zip(segments, results, audio_paths):
        if result.segment.id != segment.id:
            raise ValueError("Segment result IDs do not match the script.")
        if previous_scene_id != segment.scene_id and previous_scene_id is not None:
            cursor += float(scene_by_id[segment.scene_id].get("pause_before_sec", 0.0))
        local_end = max(
            (float(timestamp.end) for timestamp in result.word_timestamps),
            default=0.0,
        )
        if local_end <= 0.0:
            raise ValueError(f"Segment {segment.id!r} has no usable word timing.")
        start = cursor
        duration = _segment_audio_duration(audio_path, local_end)
        end = start + duration
        base_records.append((segment, result, audio_path, start, end))
        cursor = end
        previous_scene_id = segment.scene_id

    base_flattened: list[dict[str, Any]] = []
    for segment, result, _audio_path, base_start, _base_end in base_records:
        for timestamp in result.word_timestamps:
            item = timestamp.to_dict()
            item["start"] = base_start + float(timestamp.start)
            item["end"] = base_start + float(timestamp.end)
            base_flattened.append(item)

    records = []
    flattened: list[dict[str, Any]] = []
    resolved_starts: dict[str, float] = {}
    result_by_id = {
        segment.id: (segment, result, audio_path, base_start, base_end)
        for segment, result, audio_path, base_start, base_end in base_records
    }
    for segment_position, (segment, result, audio_path, base_start, base_end) in enumerate(base_records):
        if segment.start_at_word is None:
            start = base_start + segment.start_offset_sec
        else:
            reference_id = segment.relative_to
            if reference_id is None:
                previous = next(
                    (
                        item
                        for item in reversed(segments[:segment_position])
                        if item.scene_id == segment.scene_id
                    ),
                    None,
                )
                if previous is None:
                    raise ValueError(
                        f"Segment {segment.id!r} has no preceding same-scene anchor."
                    )
                reference_id = previous.id
            if reference_id not in result_by_id or reference_id not in resolved_starts:
                raise ValueError(
                    f"Segment {segment.id!r} references an unresolved preceding segment "
                    f"{reference_id!r}."
                )
            reference_segment, reference_result, _reference_audio, _reference_base_start, _reference_end = (
                result_by_id[reference_id]
            )
            word_index = segment.start_at_word - 1
            if word_index >= len(reference_result.word_timestamps):
                raise ValueError(
                    f"Segment {segment.id!r} start_at_word={segment.start_at_word} "
                    f"is outside referenced segment {reference_id!r}."
                )
            start = (
                resolved_starts[reference_segment.id]
                + float(reference_result.word_timestamps[word_index].start)
                + segment.start_offset_sec
            )
        end = start + (base_end - base_start)
        resolved_starts[segment.id] = start
        relative_audio = str(audio_path.relative_to(project_dir))
        records.append(
            {
                "id": segment.id,
                "scene_id": segment.scene_id,
                "voice_id": segment.voice_id,
                "text": segment.text,
                "audio_path": relative_audio,
                "start_sec": start,
                "end_sec": end,
                "start_time_sec": start,
                "end_time_sec": end,
                "word_timestamps": [
                    timestamp.to_dict() for timestamp in result.word_timestamps
                ],
            }
        )
        for timestamp in result.word_timestamps:
            item = timestamp.to_dict()
            item["start"] = start + float(timestamp.start)
            item["end"] = start + float(timestamp.end)
            flattened.append(item)
    scenes = _segment_scene_alignments(script, records, flattened)
    manifest = {
        "narration_hash": narration_hash(script),
        "narration_segments": records,
        "word_timestamps": flattened,
        "scenes": scenes,
        "tts_model": model,
        "speed": speed,
    }
    write_manifest(manifest_path, manifest)
    return manifest


def build_manifest(
    script: dict[str, Any],
    manifest_path: Path,
    client: NarrationClient,
) -> tuple[dict[str, Any], bool]:
    current_hash = narration_hash(script)
    if manifest_path.is_file():
        cached = read_manifest(manifest_path)
        if cached.get("narration_hash") == current_hash:
            cached_text, _ = narration_text_and_pauses(
                _scene_dicts_with_segment_text(script)
            )
            if cached_words_match(cached_text, cached.get("word_timestamps")):
                return cached, True

    if _has_segment_syntax(script):
        segment_method = getattr(client, "synthesize_segments", None)
        if segment_method is None:
            raise TypeError("Multi-voice narration clients must support synthesize_segments().")
        segments = _normalized_segments(script)
        assert segments is not None
        results = segment_method(segments)
        narrations_dir = manifest_path.parent / "narrations"
        audio_paths: list[Path] = []
        from .segment_cache import write_cached_segment

        model = _project_value(script, "tts_model", DEFAULT_TTS_MODEL)
        speed = _project_value(script, "speed", DEFAULT_TTS_SPEED)
        for result in results:
            audio_path, _ = write_cached_segment(narrations_dir, result, model, speed)
            audio_paths.append(audio_path)
        return (
            build_segment_manifest(
                script,
                manifest_path,
                manifest_path.parent,
                results,
                audio_paths,
                model,
            ),
            False,
        )

    result: NarrationResult = client.synthesize(script["scenes"])
    timestamps = [timestamp.to_dict() for timestamp in result.word_timestamps]
    audio_path = manifest_path.parent / "narration.mp3"
    audio_path.write_bytes(result.audio_bytes)
    audio_duration = _segment_audio_duration(
        audio_path,
        max((float(item["end"]) for item in timestamps), default=0.0),
    )
    scenes = align_scenes(
        script["scenes"],
        timestamps,
        narration_duration_sec=audio_duration,
    )
    manifest = {
        "narration_hash": current_hash,
        "narration_audio_path": str(audio_path),
        "tts_model": _project_value(script, "tts_model", DEFAULT_TTS_MODEL),
        "speed": _project_value(script, "speed", DEFAULT_TTS_SPEED),
        "word_timestamps": timestamps,
        "scenes": [scene.to_dict() for scene in scenes],
    }
    write_manifest(manifest_path, manifest)
    return manifest, False
