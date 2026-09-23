"""Focused tests for human-readable CLI validation errors."""

from __future__ import annotations

import json
from pathlib import Path

from creatortainment import cli


def test_validation_errors_include_nested_paths_and_constraints() -> None:
    lines = cli.format_validation_errors(
        [
            {
                "type": "string_type",
                "loc": ("scenes", 3, "elements", 0, "asset"),
                "msg": "Input should be a valid string",
                "input": {"key": "value"},
            },
            {
                "type": "greater_than",
                "loc": ("project", "fps"),
                "msg": "Input should be greater than 0",
                "input": 0,
                "ctx": {"gt": 0},
            },
        ]
    )

    output = "\n".join(lines)
    assert "scenes[3].elements[0].asset" in output
    assert "Expected a string, but got an object." in output
    assert "project.fps" in output
    assert "Input should be greater than 0" in output


def test_identical_errors_are_grouped_by_readable_message() -> None:
    lines = cli.format_validation_errors(
        [
            {
                "type": "string_type",
                "loc": ("scenes", 0, "bg"),
                "msg": "Input should be a valid string",
                "input": 1,
            },
            {
                "type": "string_type",
                "loc": ("scenes", 1, "bg"),
                "msg": "Input should be a valid string",
                "input": 2,
            },
        ]
    )

    assert len(lines) == 1
    assert "scenes[0].bg, scenes[1].bg" in lines[0]


def test_legacy_asset_registry_hint_is_reported(tmp_path: Path, capsys) -> None:
    script = {
        "project": {},
        "asset_registry": {
            "white_portrait.jpg": "assets/backgrounds/white_portrait.jpg",
            "mouse": "assets/sprites/mrmouse_laughing.png",
        },
        "scenes": [],
    }
    path = tmp_path / "legacy.json"
    path.write_text(json.dumps(script), encoding="utf-8")

    assert cli.validate_command(path) == 1
    error = capsys.readouterr().err
    assert "✗ asset_registry.white_portrait.jpg" in error
    assert "Expected an asset object, but got a string" in error
    assert "Hint: asset_registry entries must use the current object format." in error
    assert "This script appears to use the legacy string format." in error


def test_valid_script_behavior_remains_unchanged(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        cli,
        "load_script",
        lambda _path: {"project": {"tts_model": "model", "voice_id": "voice"}},
    )
    monkeypatch.setattr(
        cli,
        "validate_script",
        lambda _script, _assets: type("Result", (), {"valid": True, "errors": []})(),
    )
    monkeypatch.setattr(cli, "asset_generation_plans", lambda _script: [])
    monkeypatch.setattr(cli, "validate_elevenlabs_values", lambda *args: [])
    monkeypatch.setattr(cli, "validate_fal_models", lambda *args: [])

    assert cli.validate_command(Path("valid.json")) == 0
    assert capsys.readouterr().out == "Valid: valid.json\n"
