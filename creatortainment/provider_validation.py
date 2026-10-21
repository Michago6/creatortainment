"""Read-only provider checks for models and voices used by a script."""

from __future__ import annotations

import json
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from . import config
from .audio.tokenize import recognized_audio_tags


MODEL_CAPABILITIES: dict[str, dict[str, bool]] = {
    "eleven_v4": {"speed": False, "audio_tags": True},
    "eleven_v4_turbo": {"speed": False, "audio_tags": True},
    "eleven_v3": {"speed": False, "audio_tags": True},
    "eleven_v3_conversational": {"speed": False, "audio_tags": True},
    "eleven_flash_v2": {"speed": True, "audio_tags": False},
    "eleven_flash_v2_5": {"speed": True, "audio_tags": False},
    "eleven_multilingual_v2": {"speed": True, "audio_tags": False},
}


def validate_elevenlabs_capabilities(
    model_id: str,
    speed: float = 1.0,
    narration_texts: list[str] | None = None,
) -> list[str]:
    """Validate script features against documented model capabilities."""
    capabilities = MODEL_CAPABILITIES.get(model_id)
    tags = [
        tag
        for text in narration_texts or []
        for tag in recognized_audio_tags(text)
    ]
    errors: list[str] = []
    if capabilities is None:
        if speed != 1.0:
            errors.append(
                f"ElevenLabs model {model_id!r} has no known speed capability; "
                "non-default project.speed cannot be validated safely."
            )
        if tags:
            errors.append(
                f"ElevenLabs model {model_id!r} has no known audio-tag capability; "
                f"recognized tags {sorted(set(tags))!r} cannot be validated safely."
            )
        return errors
    if speed != 1.0 and not capabilities["speed"]:
        errors.append(
            f"ElevenLabs model {model_id!r} does not support speed control; "
            f"project.speed={speed:g} is not allowed. Use the default 1.0."
        )
    if tags and not capabilities["audio_tags"]:
        errors.append(
            f"ElevenLabs model {model_id!r} does not support audio tags; "
            f"recognized tags: {sorted(set(tags))!r}."
        )
    return errors


def _safe_error_detail(exc: Exception) -> str:
    if isinstance(exc, HTTPError):
        return f"HTTP {exc.code}"
    if isinstance(exc, URLError):
        return "network error"
    status = getattr(exc, "status_code", getattr(exc, "status", None))
    if isinstance(status, int):
        return f"HTTP {status}"
    if isinstance(exc, RuntimeError) and (
        "API key file" in str(exc) or "Missing required credential " in str(exc)
    ):
        return str(exc)
    if isinstance(exc, RuntimeError):
        return "provider error"
    return type(exc).__name__


def _safe_provider_error(provider: str, exc: Exception) -> str:
    return f"{provider} provider check unavailable: {_safe_error_detail(exc)}"


def _provider_error_code(exc: Exception) -> str | None:
    body = getattr(exc, "body", None)
    detail = body.get("detail") if isinstance(body, dict) else None
    code = detail.get("code") if isinstance(detail, dict) else None
    return code if isinstance(code, str) else None


def _voice_validation_error(voice_id: str, exc: Exception) -> str:
    if _provider_error_code(exc) == "voice_not_found":
        return (
            f"ElevenLabs voice is unavailable: {voice_id!r} — "
            "voice not found in your account.\n"
            '  Hint: If this is a shared/community voice, add it to "My Voices" '
            'on the ElevenLabs Voices page and make sure the API key has the '
            '"voices_read" permission.'
        )
    return (
        f"ElevenLabs voice is unavailable: {voice_id!r} "
        f"({_safe_error_detail(exc)})"
    )


def validate_elevenlabs_values(
    model_id: str,
    voice_id: str,
    additional_voice_ids: set[str] | None = None,
) -> list[str]:
    try:
        api_key = config.get_elevenlabs_api_key()
        from elevenlabs.client import ElevenLabs

        client = ElevenLabs(api_key=api_key)
        models = client.models.list()
        model_ids = {
            getattr(model, "model_id", getattr(model, "id", None))
            for model in models
        }
        errors: list[str] = []
        if model_id not in model_ids:
            errors.append(f"ElevenLabs model is unavailable: {model_id!r}")
        voice_ids = {voice_id}
        voice_ids.update(additional_voice_ids or set())
        for candidate in sorted(voice_ids):
            try:
                client.voices.get(candidate)
            except Exception as exc:
                errors.append(_voice_validation_error(candidate, exc))
        return errors
    except Exception as exc:
        return [_safe_provider_error("ElevenLabs", exc)]


def validate_fal_models(model_ids: set[str]) -> list[str]:
    if not model_ids:
        return []
    try:
        api_key = config.get_fal_key()
    except Exception as exc:
        return [_safe_provider_error("fal.ai", exc)]
    errors: list[str] = []
    for model_id in sorted(model_ids):
        url = (
            "https://api.fal.ai/v1/models?endpoint_id="
            + quote(model_id, safe="")
        )
        request = Request(url, headers={"Authorization": f"Key {api_key}"})
        try:
            with urlopen(request, timeout=30) as response:
                payload = json.loads(response.read())
            if not isinstance(payload, dict):
                errors.append(f"fal.ai model lookup returned invalid data: {model_id!r}")
        except HTTPError as exc:
            errors.append(f"fal.ai model is unavailable: {model_id!r} (HTTP {exc.code})")
        except (URLError, OSError, json.JSONDecodeError) as exc:
            errors.append(
                f"fal.ai provider check unavailable for {model_id!r}: "
                f"{_safe_error_detail(exc)}"
            )
    return errors
