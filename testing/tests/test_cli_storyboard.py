"""Tests for the dependency-free storyboard CLI command."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image

from creatortainment import cli
from creatortainment.schema.validate import load_script


SCRIPT = Path("testing/scripts/example_script.json")
PROJECT_SLUG = cli.project_slug(load_script(SCRIPT)["project"]["title"])


def test_storyboard_command_uses_default_project_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cli, "PROJECTS_ROOT", tmp_path / "projects")
    monkeypatch.setattr(cli, "ASSETS_ROOT", Path("testing/assets"))

    assert cli.storyboard_command(SCRIPT, None) == 0

    outputs = list((tmp_path / "projects" / PROJECT_SLUG).glob("storyboard_*.png"))
    assert len(outputs) == 1
    output = outputs[0]
    with Image.open(output) as image:
        assert image.format == "PNG"


def test_storyboard_command_supports_output_override(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cli, "PROJECTS_ROOT", tmp_path / "projects")
    monkeypatch.setattr(cli, "ASSETS_ROOT", Path("testing/assets"))

    assert cli.storyboard_command(SCRIPT, Path("iterations/second.png")) == 0

    output = tmp_path / "projects" / PROJECT_SLUG / "iterations" / "second.png"
    assert output.is_file()


def test_output_names_use_required_timestamp_formats() -> None:
    timestamp = "20260923_165012"
    assert cli.output_filename("render", timestamp=timestamp) == (
        "render_20260923_165012.mp4"
    )
    assert cli.output_filename("render", timestamp=timestamp, preview=True) == (
        "render_20260923_165012_preview.mp4"
    )
    assert cli.output_filename("storyboard", timestamp=timestamp) == (
        "storyboard_20260923_165012.png"
    )


def test_non_overwriting_path_adds_timestamp_and_resolves_collisions(
    tmp_path: Path,
) -> None:
    existing = tmp_path / "render.mp4"
    existing.write_bytes(b"first")
    first = cli.non_overwriting_path(existing, timestamp="20260923_165012")
    first.write_bytes(b"second")
    second = cli.non_overwriting_path(existing, timestamp="20260923_165012")

    assert first.name == "render_20260923_165012.mp4"
    assert second.name == "render_20260923_165013.mp4"
    assert existing.read_bytes() == b"first"


def test_storyboard_command_rejects_invalid_script_without_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = json.loads(SCRIPT.read_text(encoding="utf-8"))
    source["scenes"][0]["bg"] = "missing_background"
    script_path = tmp_path / "invalid.json"
    script_path.write_text(json.dumps(source), encoding="utf-8")
    monkeypatch.setattr(cli, "PROJECTS_ROOT", tmp_path / "projects")
    monkeypatch.setattr(cli, "ASSETS_ROOT", Path("testing/assets"))

    assert cli.storyboard_command(script_path, None) == 1
    assert not (tmp_path / "projects" / "example_script").exists()
