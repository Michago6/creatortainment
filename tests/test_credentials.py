"""Tests for centralized repository credential loading."""

from __future__ import annotations

from pathlib import Path

import pytest

from creatortainment import config
from creatortainment import provider_validation
import generate_assets


def test_credentials_load_from_environment(monkeypatch) -> None:
    monkeypatch.setenv("FAL_KEY", "fal-test")
    monkeypatch.setenv("ELEVENLABS_API_KEY", "eleven-test")

    assert config.get_fal_key() == "fal-test"
    assert config.get_elevenlabs_api_key() == "eleven-test"


def test_credentials_load_from_repository_env_file(monkeypatch, tmp_path) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text(
        "FAL_KEY=fal-file\nELEVENLABS_API_KEY=eleven-file\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("FAL_KEY", raising=False)
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    monkeypatch.setattr(config, "ENV_PATH", env_path)

    assert config.get_fal_key() == "fal-file"
    assert config.get_elevenlabs_api_key() == "eleven-file"


@pytest.mark.parametrize("name", ["FAL_KEY", "ELEVENLABS_API_KEY"])
def test_missing_credentials_name_environment_variable(monkeypatch, tmp_path, name) -> None:
    monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(config, "ENV_PATH", tmp_path / ".env")

    with pytest.raises(RuntimeError, match=f"Missing required credential {name}"):
        config.get_credential(name)


def test_missing_credential_error_never_contains_value(monkeypatch, tmp_path) -> None:
    secret_name = "FAL_KEY"
    monkeypatch.delenv(secret_name, raising=False)
    monkeypatch.setattr(config, "ENV_PATH", tmp_path / ".env")

    with pytest.raises(RuntimeError) as raised:
        config.get_credential(secret_name)

    assert secret_name in str(raised.value)
    assert "fal-test-secret" not in str(raised.value)


def test_provider_checks_use_the_centralized_loader(monkeypatch) -> None:
    fal_error = RuntimeError("Missing required credential FAL_KEY")
    eleven_error = RuntimeError("Missing required credential ELEVENLABS_API_KEY")
    monkeypatch.setattr(provider_validation.config, "get_fal_key", lambda: (_ for _ in ()).throw(fal_error))
    monkeypatch.setattr(
        provider_validation.config,
        "get_elevenlabs_api_key",
        lambda: (_ for _ in ()).throw(eleven_error),
    )

    assert provider_validation.validate_fal_models({"model"}) == [
        "fal.ai provider check unavailable: Missing required credential FAL_KEY"
    ]
    assert provider_validation.validate_elevenlabs_values("model", "voice") == [
        "ElevenLabs provider check unavailable: Missing required credential ELEVENLABS_API_KEY"
    ]
    assert generate_assets.config is config
