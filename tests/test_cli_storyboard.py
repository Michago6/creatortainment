"""Tests for the dependency-free storyboard CLI command."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image

from creatortainment import cli
from creatortainment.schema.validate import load_script


SCRIPT = Path("scripts/testing_scripts/example_script.json")
PROJECT_SLUG = cli.project_slug(load_script(SCRIPT)["project"]["title"])


def test_storyboard_command_uses_default_project_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cli, "PROJECTS_ROOT", tmp_path / "projects")
    monkeypatch.setattr(cli, "ASSETS_ROOT", Path("assets"))

    assert cli.storyboard_command(SCRIPT, None) == 0

    output = tmp_path / "projects" / PROJECT_SLUG / "storyboard.png"
    assert output.is_file()
    with Image.open(output) as image:
        assert image.format == "PNG"


def test_storyboard_command_supports_output_override(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cli, "PROJECTS_ROOT", tmp_path / "projects")
    monkeypatch.setattr(cli, "ASSETS_ROOT", Path("assets"))

    assert cli.storyboard_command(SCRIPT, Path("iterations/second.png")) == 0

    output = tmp_path / "projects" / PROJECT_SLUG / "iterations" / "second.png"
    assert output.is_file()


def test_storyboard_command_rejects_invalid_script_without_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = json.loads(SCRIPT.read_text(encoding="utf-8"))
    source["scenes"][0]["bg"] = "missing_background"
    script_path = tmp_path / "invalid.json"
    script_path.write_text(json.dumps(source), encoding="utf-8")
    monkeypatch.setattr(cli, "PROJECTS_ROOT", tmp_path / "projects")
    monkeypatch.setattr(cli, "ASSETS_ROOT", Path("assets"))

    assert cli.storyboard_command(script_path, None) == 1
    assert not (tmp_path / "projects" / "example_script" / "storyboard.png").exists()
