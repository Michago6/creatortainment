"""Tests project state persistence without invoking the live ElevenLabs API."""

from datetime import datetime, timezone

from pathlib import Path

from creatortainment.project_identity import (
    new_state,
    project_state_path,
    slugify,
    variant_manifest_path,
    write_project_state,
)


def test_new_project_state_contains_stable_identity_data(tmp_path) -> None:
    """A new project state records title, date, model, hash, and update time."""
    script = {
        "project": {"title": "My Video!", "date": "2026-09-16", "tts_model": "eleven_flash_v2_5"},
        "scenes": [{"narration_text": "Hello world."}],
    }
    project_dir = tmp_path / slugify(script["project"]["title"])
    project_dir.mkdir()
    state = new_state(script, datetime(2026, 9, 16, tzinfo=timezone.utc))
    write_project_state(project_state_path(project_dir), state)
    assert project_state_path(project_dir).is_file()
    assert state["title"] == "My Video!"
    assert state["tts_model"] == "eleven_flash_v2_5"


def test_variant_manifest_paths_are_separate_within_one_project(tmp_path: Path) -> None:
    """Different script filenames get separate manifests under one stable project."""
    project_dir = tmp_path / "my_video"
    portrait = variant_manifest_path(project_dir, Path("example_script.json"))
    landscape = variant_manifest_path(project_dir, Path("example_script_extended_horizontal.json"))
    assert portrait != landscape
    assert portrait.parent == landscape.parent == project_dir / "build_manifests"
