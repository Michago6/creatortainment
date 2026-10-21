"""Tests for provider-aware validation and generation-plan reporting."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from creatortainment import cli
from creatortainment import provider_validation
from creatortainment.schema.models import ScriptModel
from creatortainment.schema.validate import asset_generation_plans, validate_script


@pytest.mark.parametrize(
    "model",
    ["eleven_v3", "eleven_v3_conversational", "eleven_v4", "eleven_v4_turbo"],
)
def test_v4_models_reject_non_default_speed_but_allow_tags(model: str) -> None:
    errors = provider_validation.validate_elevenlabs_capabilities(
        model, 1.1, ["[whispers] Hello."]
    )
    assert any("does not support speed control" in error for error in errors)
    assert not any("audio tags" in error for error in errors)


@pytest.mark.parametrize(
    "model",
    ["eleven_v3", "eleven_v3_conversational", "eleven_v4", "eleven_v4_turbo"],
)
def test_tag_models_accept_omitted_or_default_speed(model: str) -> None:
    assert provider_validation.validate_elevenlabs_capabilities(model) == []
    assert provider_validation.validate_elevenlabs_capabilities(model, 1.0) == []


def test_speed_capability_accepts_default_and_rejects_tags_for_flash() -> None:
    assert provider_validation.validate_elevenlabs_capabilities(
        "eleven_flash_v2_5", 1.0, []
    ) == []
    errors = provider_validation.validate_elevenlabs_capabilities(
        "eleven_flash_v2_5", 1.0, ["[laughs] Hello."]
    )
    assert any("does not support audio tags" in error for error in errors)


def test_ordinary_bracketed_text_is_not_treated_as_audio_tag() -> None:
    assert provider_validation.validate_elevenlabs_capabilities(
        "eleven_flash_v2_5", 1.0, ["Use [section 2] for details."]
    ) == []


def test_multi_voice_tag_capability_checks_each_segment() -> None:
    errors = provider_validation.validate_elevenlabs_capabilities(
        "eleven_flash_v2_5",
        1.0,
        ["First line.", "[curious] Second line."],
    )
    assert len(errors) == 1
    assert "curious" in errors[0]


def script_with_assets(
    generated: dict | None = None,
    *,
    defaults: dict | None = None,
) -> dict:
    registry = {
        "background": {
            "path": "assets/backgrounds/default_studio.jpg",
            "generate": None,
        }
    }
    if generated is not None:
        registry["generated"] = generated
    return {
        "project": {
            "title": "Validation",
            "aspect_ratio": "9:16",
            "resolution": [1080, 1920],
            "fps": 30,
            "voice_id": "voice",
            "tts_model": "eleven_model",
            "generation_defaults": defaults or {},
        },
        "asset_registry": registry,
        "scenes": [
            {
                "id": "scene_1",
                "bg": "background",
                "narration_text": "Hello",
                "transition_in": None,
            }
        ],
    }


def generation(method: str = "text_to_image", model: str | None = None) -> dict:
    return {
        "asset_type": "background",
        "generation_method": method,
        "model": model,
        "description": "test",
        "source_asset": None,
        "transparent_background": False,
    }


def test_missing_and_null_generation_defaults_are_equivalent() -> None:
    missing = script_with_assets(
        {"path": "assets/generated.jpg", "generate": generation()},
    )
    explicit_null = script_with_assets(
        {"path": "assets/generated.jpg", "generate": generation()},
        defaults={"text_to_image": None},
    )
    assert asset_generation_plans(ScriptModel.model_validate(missing))[0].effective_model is None
    assert asset_generation_plans(ScriptModel.model_validate(explicit_null))[0].effective_model is None


def test_unused_invalid_default_does_not_need_provider_validation(
    monkeypatch,
) -> None:
    script = script_with_assets(
        {"path": "assets/generated.jpg", "generate": generation()},
        defaults={"text_to_image": "required-model", "image_to_image": "unused-invalid"}
    )
    model = ScriptModel.model_validate(script)
    calls: list[set[str]] = []
    monkeypatch.setattr(cli, "validate_elevenlabs_values", lambda *args: [])
    monkeypatch.setattr(
        cli,
        "validate_fal_models",
        lambda models: calls.append(models) or [],
    )
    monkeypatch.setattr(cli, "load_script", lambda _path: model)
    assert cli.validate_command(Path("script.json")) == 0
    assert calls == [{"required-model"}]


def test_required_model_default_override_and_missing_are_reported(
    monkeypatch,
    capsys,
) -> None:
    script = script_with_assets(
        {
            "path": "assets/generated.jpg",
            "generate": generation(model=None),
        },
        defaults={},
    )
    model = ScriptModel.model_validate(script)
    monkeypatch.setattr(cli, "load_script", lambda _path: model)
    monkeypatch.setattr(cli, "validate_elevenlabs_values", lambda *args: [])
    monkeypatch.setattr(cli, "validate_fal_models", lambda *args: [])
    assert cli.validate_command(Path("script.json")) == 1
    error = capsys.readouterr().err
    assert "Asset generation:" in error
    assert "- No model configured for text_to_image (1 assets)" in error
    assert "asset_registry['generated']" not in error


def test_missing_generation_models_are_grouped_by_method(monkeypatch, capsys) -> None:
    script = script_with_assets(
        {
            "path": "assets/generated-image.jpg",
            "generate": generation(method="text_to_image"),
        }
    )
    script["asset_registry"]["generated_image_2"] = {
        "path": "assets/generated-image-2.jpg",
        "generate": generation(method="text_to_image"),
    }
    script["asset_registry"]["generated_audio"] = {
        "path": "assets/generated-audio.mp3",
        "generate": generation(method="text_to_audio"),
    }
    model = ScriptModel.model_validate(script)
    monkeypatch.setattr(cli, "load_script", lambda _path: model)
    monkeypatch.setattr(cli, "validate_elevenlabs_values", lambda *args: [])
    monkeypatch.setattr(cli, "validate_fal_models", lambda *args: [])

    assert cli.validate_command(Path("script.json")) == 1
    error = capsys.readouterr().err
    assert "Asset generation:" in error
    assert "- No model configured for text_to_image (2 assets)" in error
    assert "- No model configured for text_to_audio (1 assets)" in error
    assert "generated-image" not in error
    assert "generated-audio" not in error


def test_provider_validation_receives_only_required_models(monkeypatch) -> None:
    script = script_with_assets(
        {
            "path": "assets/generated.jpg",
            "generate": generation(model="asset-override"),
        },
        defaults={"text_to_image": "unused-default"},
    )
    model = ScriptModel.model_validate(script)
    monkeypatch.setattr(cli, "load_script", lambda _path: model)
    monkeypatch.setattr(cli, "validate_elevenlabs_values", lambda *args: [])
    calls = []
    monkeypatch.setattr(
        cli,
        "validate_fal_models",
        lambda models: calls.append(models) or [],
    )
    assert cli.validate_command(Path("script.json")) == 0
    assert calls == [{"asset-override"}]


def test_asset_gen_info_reports_generated_only_and_unresolved(
    monkeypatch,
    capsys,
) -> None:
    script = script_with_assets(
        {
            "path": "assets/generated.jpg",
            "generate": generation(method="text_to_image", model="override"),
        },
        defaults={},
    )
    script["asset_registry"]["static"] = {
        "path": "assets/backgrounds/default_studio.jpg",
        "generate": None,
    }
    model = ScriptModel.model_validate(script)
    monkeypatch.setattr(cli, "load_script", lambda _path: model)
    monkeypatch.setattr(cli, "validate_elevenlabs_values", lambda *args: [])
    monkeypatch.setattr(cli, "validate_fal_models", lambda *args: [])
    assert cli.validate_command(Path("script.json"), asset_gen_info=True) == 0
    output = capsys.readouterr().out
    assert "generated: method=text_to_image, model=override" in output
    assert "static" not in output

    script["asset_registry"]["generated"]["generate"]["model"] = None
    model = ScriptModel.model_validate(script)
    monkeypatch.setattr(cli, "load_script", lambda _path: model)
    assert cli.validate_command(Path("script.json"), asset_gen_info=True) == 1
    output = capsys.readouterr().out
    assert "generated: method=text_to_image, model=<unresolved>" in output


def test_voice_not_found_reports_account_hint(monkeypatch, tmp_path) -> None:
    import elevenlabs.client

    class FakeProviderError(Exception):
        def __init__(self, body) -> None:
            self.body = body

    class FakeElevenLabs:
        def __init__(self, *, api_key: str) -> None:
            assert api_key == "test-key"
            self.models = SimpleNamespace(
                list=lambda: [SimpleNamespace(model_id="eleven_v3")]
            )
            self.voices = SimpleNamespace(
                get=lambda _voice_id: (_ for _ in ()).throw(
                    FakeProviderError(
                        {
                            "detail": {
                                "code": "voice_not_found",
                                "type": "not_found",
                                "message": "provider detail",
                            }
                        }
                    )
                )
            )

    monkeypatch.setattr(provider_validation.config, "get_elevenlabs_api_key", lambda: "test-key")
    monkeypatch.setattr(elevenlabs.client, "ElevenLabs", FakeElevenLabs)

    errors = provider_validation.validate_elevenlabs_values(
        "eleven_v3",
        "missing-voice",
    )

    assert errors == [
        "ElevenLabs voice is unavailable: 'missing-voice' — "
        "voice not found in your account.\n"
        '  Hint: If this is a shared/community voice, add it to "My Voices" '
        'on the ElevenLabs Voices page and make sure the API key has the '
        '"voices_read" permission.'
    ]
    assert "provider detail" not in errors[0]
    assert "headers" not in errors[0]


def test_other_voice_provider_errors_remain_distinct(monkeypatch, tmp_path) -> None:
    import elevenlabs.client

    class FakeProviderError(Exception):
        status_code = 401
        body = {"detail": {"code": "missing_permissions"}}

    class FakeElevenLabs:
        def __init__(self, *, api_key: str) -> None:
            self.models = SimpleNamespace(
                list=lambda: [SimpleNamespace(model_id="eleven_v3")]
            )
            self.voices = SimpleNamespace(
                get=lambda _voice_id: (_ for _ in ()).throw(FakeProviderError())
            )

    monkeypatch.setattr(provider_validation.config, "get_elevenlabs_api_key", lambda: "test-key")
    monkeypatch.setattr(elevenlabs.client, "ElevenLabs", FakeElevenLabs)

    errors = provider_validation.validate_elevenlabs_values(
        "eleven_v3",
        "restricted-voice",
    )

    assert errors == [
        "ElevenLabs voice is unavailable: 'restricted-voice' (HTTP 401)"
    ]


def test_segment_voice_provider_errors_are_checked(monkeypatch) -> None:
    import elevenlabs.client

    class FakeElevenLabs:
        def __init__(self, *, api_key: str) -> None:
            self.models = SimpleNamespace(
                list=lambda: [SimpleNamespace(model_id="eleven_v3")]
            )
            self.voices = SimpleNamespace(
                get=lambda voice_id: (
                    None
                    if voice_id == "default-voice"
                    else (_ for _ in ()).throw(RuntimeError("missing"))
                )
            )

    monkeypatch.setattr(provider_validation.config, "get_elevenlabs_api_key", lambda: "test-key")
    monkeypatch.setattr(elevenlabs.client, "ElevenLabs", FakeElevenLabs)

    errors = provider_validation.validate_elevenlabs_values(
        "eleven_v3",
        "default-voice",
        {"segment-voice"},
    )

    assert errors == [
        "ElevenLabs voice is unavailable: 'segment-voice' (provider error)"
    ]
