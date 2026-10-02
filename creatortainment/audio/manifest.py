"""Build manifest persistence and narration cache handling."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any

from .alignment import align_scenes
from .elevenlabs_client import NarrationClient, NarrationResult, narration_text_and_pauses
from .tokenize import tokenize

DEFAULT_TTS_MODEL = "eleven_flash_v2_5"


def narration_hash(script: dict[str, Any]) -> str:
    text, _ = narration_text_and_pauses(script["scenes"])
    model = script.get("project", {}).get("tts_model", DEFAULT_TTS_MODEL)
    return narration_hash_for_text(text, model)


def narration_hash_for_text(text: str, model: str = DEFAULT_TTS_MODEL) -> str:
    """Return the cache hash used for narration sidecar text and model."""
    return hashlib.sha256(f"{text}\n{model}".encode("utf-8")).hexdigest()


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

    text, _ = narration_text_and_pauses(script["scenes"])
    expected_words = tokenize(text)
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
    if validate_audio_duration:
        from moviepy import AudioFileClip

        audio = AudioFileClip(str(audio_path))
        try:
            if previous_end > float(audio.duration) + 0.001:
                raise ValueError(
                    "Cached narration audio is shorter than its word timestamps. "
                    "Run align before rendering."
                )
        finally:
            audio.close()

    aligned_scenes = [
        scene.to_dict() for scene in align_scenes(script["scenes"], timestamps)
    ]
    changed = manifest.get("scenes") != aligned_scenes
    if changed:
        manifest["scenes"] = aligned_scenes
    return changed


def build_manifest(
    script: dict[str, Any],
    manifest_path: Path,
    client: NarrationClient,
) -> tuple[dict[str, Any], bool]:
    current_hash = narration_hash(script)
    if manifest_path.is_file():
        cached = read_manifest(manifest_path)
        if cached.get("narration_hash") == current_hash:
            return cached, True

    result: NarrationResult = client.synthesize(script["scenes"])
    timestamps = [timestamp.to_dict() for timestamp in result.word_timestamps]
    scenes = align_scenes(script["scenes"], timestamps)
    audio_path = manifest_path.parent / "narration.mp3"
    audio_path.write_bytes(result.audio_bytes)
    manifest = {
        "narration_hash": current_hash,
        "narration_audio_path": str(audio_path),
        "word_timestamps": timestamps,
        "scenes": [scene.to_dict() for scene in scenes],
    }
    write_manifest(manifest_path, manifest)
    return manifest, False
