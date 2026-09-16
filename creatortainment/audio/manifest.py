"""Build manifest persistence and narration cache handling."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .alignment import align_scenes
from .elevenlabs_client import NarrationClient, NarrationResult, narration_text_and_pauses


def narration_hash(script: dict[str, Any]) -> str:
    text, _ = narration_text_and_pauses(script["scenes"])
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


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
