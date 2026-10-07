"""Offline tests for storyboard-first alignment initialization."""

from __future__ import annotations

import json
from pathlib import Path

from creatortainment import cli
from creatortainment.audio.elevenlabs_client import NarrationResult, WordTimestamp
from creatortainment.project_identity import project_state_path


ROOT = Path(__file__).parents[2]
ASSETS = ROOT / "testing/assets"


def _script() -> dict:
    return {
        "project": {
            "title": "Storyboard First Align Test",
            "date": "2026-09-23",
            "tts_model": "eleven_flash_v2_5",
            "voice_id": "offline-test-voice",
            "aspect_ratio": "9:16",
            "resolution": [1080, 1920],
            "fps": 30,
        },
        "asset_registry": {
            "background": {
                "path": "assets/backgrounds/white_portrait.jpg",
                "generate": None,
            }
        },
        "scenes": [
            {
                "id": "scene_1",
                "bg": "background",
                "narration_text": "Storyboard first alignment.",
                "transition_in": None,
                "elements": [],
            }
        ],
    }


class FakeNarrationClient:
    calls = 0

    def __init__(self, api_key: str, **kwargs) -> None:
        self.api_key = api_key

    def synthesize(self, scenes: list[dict]) -> NarrationResult:
        type(self).calls += 1
        words = " ".join(scene["narration_text"] for scene in scenes).split()
        return NarrationResult(
            audio_bytes=b"offline-audio",
            word_timestamps=[
                WordTimestamp(word, index * 0.4, index * 0.4 + 0.3)
                for index, word in enumerate(words)
            ],
            pause_before_sec=[],
        )


def _prepare(
    tmp_path: Path,
    monkeypatch,
) -> tuple[Path, Path]:
    script_path = tmp_path / "script.json"
    script_path.write_text(json.dumps(_script()), encoding="utf-8")
    monkeypatch.setattr(cli, "PROJECTS_ROOT", tmp_path / "projects")
    monkeypatch.setattr(cli, "ASSETS_ROOT", ASSETS)
    monkeypatch.setattr(cli.config, "get_elevenlabs_api_key", lambda: "offline-key")
    FakeNarrationClient.calls = 0
    monkeypatch.setattr(cli, "ElevenLabsNarrationClient", FakeNarrationClient)
    project_dir = tmp_path / "projects" / "storyboard_first_align_test"
    return script_path, project_dir


def test_storyboard_then_align_initializes_partial_project_without_prompt(
    tmp_path: Path,
    monkeypatch,
) -> None:
    script_path, project_dir = _prepare(tmp_path, monkeypatch)

    assert cli.storyboard_command(script_path, None) == 0
    assert len(list(project_dir.glob("storyboard_*.png"))) == 1
    assert not project_state_path(project_dir).exists()

    assert cli.align_command(script_path, force_audio=False, debug=False) == 0
    assert project_state_path(project_dir).is_file()
    assert FakeNarrationClient.calls == 1


def test_partial_project_with_debug_still_initializes_state(
    tmp_path: Path,
    monkeypatch,
) -> None:
    script_path, project_dir = _prepare(tmp_path, monkeypatch)
    assert cli.storyboard_command(script_path, None) == 0

    assert cli.align_command(script_path, force_audio=False, debug=True) == 0
    assert project_state_path(project_dir).is_file()
    assert (project_dir / "debug.log").is_file()


def test_initialized_project_keeps_confirmation_flow(
    tmp_path: Path,
    monkeypatch,
) -> None:
    script_path, project_dir = _prepare(tmp_path, monkeypatch)
    assert cli.align_command(script_path, force_audio=False, debug=False) == 0
    assert project_state_path(project_dir).is_file()
    monkeypatch.setattr("builtins.input", lambda prompt: "n")

    assert cli.align_command(script_path, force_audio=False, debug=False) == 0
    assert FakeNarrationClient.calls == 1


def test_matching_narration_reuse_and_force_audio_behavior(
    tmp_path: Path,
    monkeypatch,
) -> None:
    script_path, project_dir = _prepare(tmp_path, monkeypatch)
    assert cli.align_command(script_path, force_audio=False, debug=False) == 0
    assert FakeNarrationClient.calls == 1
    monkeypatch.setattr("builtins.input", lambda prompt: "y")

    assert cli.align_command(script_path, force_audio=False, debug=False) == 0
    assert FakeNarrationClient.calls == 1

    assert cli.align_command(script_path, force_audio=True, debug=False) == 0
    assert FakeNarrationClient.calls == 2
