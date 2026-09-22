"""Offline tests for current-format asset generation."""

from __future__ import annotations

from pathlib import Path

import pytest

from creatortainment.asset_generation import (
    AssetGenerationError,
    GenerationRequest,
    build_generation_request,
    generate_assets,
)
from creatortainment.cli import generate_assets_command
from creatortainment.schema.models import ScriptModel


def make_script() -> dict:
    return {
        "project": {
            "title": "Generation",
            "aspect_ratio": "9:16",
            "resolution": [1080, 1920],
            "fps": 30,
            "voice_id": "voice",
            "tts_model": "eleven_flash_v2_5",
            "generation_defaults": {
                "text_to_image": "image-default",
                "image_to_image": "image-override-default",
                "text_to_audio": "audio-default",
                "audio_to_audio": "audio-override-default",
            },
        },
        "asset_registry": {
            "text": {
                "path": "assets/out/text.png",
                "generate": {
                    "asset_type": "background",
                    "generation_method": "text_to_image",
                    "description": "text image",
                    "transparent_background": False,
                },
            },
            "image": {
                "path": "assets/out/image.png",
                "generate": {
                    "asset_type": "sprite",
                    "generation_method": "image_to_image",
                    "description": "image transform",
                    "source_asset": "image_source",
                    "transparent_background": True,
                },
            },
            "image_source": {
                "path": "assets/source.png",
                "generate": None,
            },
            "text_audio": {
                "path": "assets/out/text.mp3",
                "generate": {
                    "asset_type": "sfx",
                    "generation_method": "text_to_audio",
                    "description": "text sound",
                    "transparent_background": None,
                },
            },
            "audio": {
                "path": "assets/out/audio.mp3",
                "generate": {
                    "asset_type": "sfx",
                    "generation_method": "audio_to_audio",
                    "description": "audio transform",
                    "source_asset": "audio_source",
                    "transparent_background": None,
                    "model": "audio-override",
                },
            },
            "audio_source": {
                "path": "assets/source.mp3",
                "generate": None,
            },
        },
        "scenes": [
            {
                "id": "scene",
                "bg": "text",
                "narration_text": "test",
                "transition_in": None,
            }
        ],
    }


class FakeProvider:
    def __init__(self, outputs: bytes = b"generated") -> None:
        self.requests: list[GenerationRequest] = []
        self.outputs = outputs

    def generate(self, request: GenerationRequest) -> bytes:
        self.requests.append(request)
        return self.outputs


def test_all_four_requests_use_effective_models_and_resolution(tmp_path) -> None:
    root = tmp_path / "assets"
    root.mkdir()
    (root / "source.png").write_bytes(b"png")
    (root / "source.mp3").write_bytes(b"mp3")
    (root / "source.mp3").write_bytes(b"mp3")
    script = ScriptModel.model_validate(make_script())
    provider = FakeProvider()

    generated, skipped, failed = generate_assets(script, root, provider=provider)

    assert generated == ["text", "image", "text_audio", "audio"]
    assert skipped == []
    assert failed == []
    assert [request.model for request in provider.requests] == [
        "image-default",
        "image-override-default",
        "audio-default",
        "audio-override",
    ]
    assert provider.requests[0].payload == {
        "prompt": "text image",
        "image_size": {"width": 1080, "height": 1920},
    }
    assert provider.requests[1].payload["image_size"] == {
        "width": 1080,
        "height": 1920,
    }
    assert provider.requests[1].payload["image_url"].startswith("data:image/png;base64,")
    assert provider.requests[2].payload == {"text_prompt": "text sound"}
    assert provider.requests[3].payload["prompt"] == "audio transform"
    assert provider.requests[3].payload["audio_url"].startswith("data:audio/mpeg;base64,")
    assert all(path.is_file() for path in [
        root / "out/text.png",
        root / "out/image.png",
        root / "out/text.mp3",
        root / "out/audio.mp3",
    ])


def test_dependencies_are_ordered_and_existing_assets_are_skipped(tmp_path) -> None:
    root = tmp_path / "assets"
    (root / "source.png").parent.mkdir(parents=True)
    (root / "source.png").write_bytes(b"source")
    (root / "source.mp3").write_bytes(b"source")
    (root / "out").mkdir()
    (root / "out/text.png").write_bytes(b"existing")
    script = ScriptModel.model_validate(make_script())
    provider = FakeProvider()

    generated, skipped, failed = generate_assets(script, root, provider=provider)

    assert "text" in skipped
    assert generated == ["image", "text_audio", "audio"]
    assert [request.asset_key for request in provider.requests] == [
        "image",
        "text_audio",
        "audio",
    ]
    assert failed == []


def test_force_regenerates_existing_assets(tmp_path) -> None:
    root = tmp_path / "assets"
    root.mkdir()
    (root / "source.png").write_bytes(b"source")
    (root / "source.mp3").write_bytes(b"source")
    (root / "out").mkdir()
    (root / "out/text.png").write_bytes(b"old")
    script = ScriptModel.model_validate(make_script())
    provider = FakeProvider(b"new")

    generated, skipped, failed = generate_assets(
        script, root, force=True, provider=provider
    )

    assert "text" in generated
    assert skipped == []
    assert failed == []
    assert (root / "out/text.png").read_bytes() == b"new"


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ("missing_source", "source asset file does not exist"),
        ("cycle", "circular generation dependency"),
        ("missing_model", "no effective model configured"),
    ],
)
def test_generation_failures_are_reported(tmp_path, change, message) -> None:
    root = tmp_path / "assets"
    script_data = make_script()
    if change == "missing_source":
        script_data["asset_registry"]["image_source"]["path"] = "assets/missing.png"
    elif change == "cycle":
        script_data["asset_registry"]["image"]["generate"]["source_asset"] = "audio"
        script_data["asset_registry"]["audio"]["generate"]["source_asset"] = "image"
    else:
        script_data["project"]["generation_defaults"]["text_to_image"] = None
        script_data["asset_registry"]["text"]["generate"]["model"] = None
    script = ScriptModel.model_validate(script_data)
    provider = FakeProvider()

    if change == "cycle":
        with pytest.raises(AssetGenerationError, match=message):
            generate_assets(script, root, provider=provider)
    else:
        _, _, failed = generate_assets(script, root, provider=provider)
        assert any(message in error for error in failed)


def test_cli_reports_failures_and_exit_code(monkeypatch, tmp_path, capsys) -> None:
    script = ScriptModel.model_validate(make_script())
    monkeypatch.setattr(
        "creatortainment.cli.load_script",
        lambda _path: script,
    )
    monkeypatch.setattr(
        "creatortainment.cli.validate_script",
        lambda *_args: type("Result", (), {"valid": True, "errors": []})(),
    )
    monkeypatch.setattr(
        "creatortainment.cli.generate_assets",
        lambda *args, **kwargs: ([], [], ["text: provider unavailable"]),
    )

    assert generate_assets_command(Path("script.json"), False) == 1
    assert "Failed: text: provider unavailable" in capsys.readouterr().err
