"""Tests narration-sidecar lookup across retained narration history."""

from __future__ import annotations

import json
from pathlib import Path

from creatortainment.audio.manifest import narration_hash_for_text
from creatortainment.cli import find_matching_narration


def _write_sidecar(
    project_dir: Path,
    filename: str,
    text: str,
    model: str,
) -> None:
    narrations = project_dir / "narrations"
    narrations.mkdir(parents=True, exist_ok=True)
    (narrations / filename).with_suffix(".mp3").write_bytes(b"audio")
    (narrations / filename).with_suffix(".json").write_text(
        json.dumps(
            {
                "narration_text": text,
                "tts_model": model,
                "word_timestamps": [{"start": 0.0, "end": 0.5, "word": "Hello"}],
            }
        ),
        encoding="utf-8",
    )


def test_lookup_reuses_older_matching_narration(tmp_path: Path) -> None:
    """A matching older sidecar is found even when another narration is newer."""
    project = tmp_path / "project"
    _write_sidecar(project, "older", "Older narration.", "model")
    _write_sidecar(project, "newer", "Current narration.", "model")

    match = find_matching_narration(
        project,
        narration_hash_for_text("Older narration.", "model"),
    )

    assert match is not None
    assert match[0].name == "older.mp3"
    assert match[1][0]["word"] == "Hello"


def test_lookup_returns_none_for_new_narration(tmp_path: Path) -> None:
    """A narration absent from all sidecars remains eligible for generation."""
    project = tmp_path / "project"
    _write_sidecar(project, "existing", "Existing narration.", "model")

    assert find_matching_narration(
        project,
        narration_hash_for_text("Not present.", "model"),
    ) is None
