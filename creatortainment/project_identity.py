"""Stable project folders, narration history, and confirmation decisions."""

from __future__ import annotations

import json
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .audio.manifest import DEFAULT_TTS_MODEL, narration_hash


def slugify(title: str, max_length: int = 80) -> str:
    """Create a deterministic, Unicode-aware underscore-separated project slug."""
    normalized = unicodedata.normalize("NFKC", title).strip().lower()
    value = re.sub(r"[^\w]+", "_", normalized, flags=re.UNICODE).strip("_")
    return (value or "untitled_project")[:max_length].rstrip("_")


def project_state_path(project_dir: Path) -> Path:
    return project_dir / "project_state.json"


def read_project_state(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValueError(f"Could not read project state {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"Project state {path} contains invalid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError("Project state must be a JSON object.")
    return value


def write_project_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def new_state(script: dict[str, Any], now: datetime | None = None) -> dict[str, Any]:
    current = now or datetime.now(timezone.utc)
    project = script["project"]
    return {
        "title": project["title"],
        "date": project.get("date"),
        "narration_hash": narration_hash(script),
        "tts_model": project.get("tts_model", DEFAULT_TTS_MODEL),
        "updated_at": current.isoformat(),
    }


def confirm_update(title: str, existing: dict[str, Any], input_fn: Callable[[str], str]) -> bool:
    print(f"A project named '{title}' already exists (last updated {existing.get('updated_at', 'unknown')}).")
    if existing.get("narration_hash") == existing.get("_incoming_narration_hash"):
        print("Same audio description detected. New audio won't be created.")
    else:
        print(
            "A new audio for this project will be created. The existing narration "
            "will not be overwritten — a new file will be added to this project's narrations/ folder."
        )
    answer = input_fn(f"Update existing project '{title}' with this script? [y/N] ")
    return answer.strip().lower() in {"y", "yes"}
