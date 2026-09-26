"""Tests for the typed authored-script schema."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from creatortainment.schema.models import (
    BgMusicStartModel,
    BgMusicStopModel,
    CrossfadeTransitionModel,
    PushTransitionModel,
    ScriptModel,
    ZoomOutTransitionModel,
)
from creatortainment.schema.validate import load_script, validate_script


ROOT = Path(__file__).parents[1]
SCRIPTS = ROOT / "scripts/testing_scripts"


def test_all_testing_scripts_load_as_typed_models() -> None:
    for path in sorted(SCRIPTS.glob("*.json")):
        model = load_script(path)
        result = validate_script(model, ROOT / "assets")
        assert isinstance(model, ScriptModel)
        assert result.valid, result.errors


def test_transition_union_parses_all_shapes() -> None:
    base = json.loads(
        (SCRIPTS / "example_script_transitions.json").read_text(encoding="utf-8")
    )
    scenes = base["scenes"]
    assert scenes[1]["transition_in"]["type"] == "crossfade"
    assert scenes[2]["transition_in"]["type"] == "zoom_out"
    assert scenes[3]["transition_in"]["type"] == "push"
    model = ScriptModel.model_validate(base)
    assert isinstance(model.scenes[1].transition_in, CrossfadeTransitionModel)
    assert isinstance(model.scenes[2].transition_in, ZoomOutTransitionModel)
    assert isinstance(model.scenes[3].transition_in, PushTransitionModel)
    assert model.scenes[4].transition_in is not None


def test_music_union_supports_legacy_start_and_stop_shapes() -> None:
    script = json.loads(
        (SCRIPTS / "example_script_music_pause.json").read_text(encoding="utf-8")
    )
    model = ScriptModel.model_validate(script)
    assert isinstance(model.scenes[0].bg_music, BgMusicStartModel)
    assert isinstance(model.scenes[1].bg_music, BgMusicStopModel)


@pytest.mark.parametrize(
    "transition",
    [
        {"type": "push", "style": "hard", "duration_sec": 0.3},
        {"type": "zoom_out", "duration_sec": 0.3, "zoom_scale": 1.0},
        {"type": "crossfade"},
        {"type": "unknown", "duration_sec": 0.3},
    ],
)
def test_invalid_transition_shapes_are_rejected(transition: dict) -> None:
    script = json.loads(
        (SCRIPTS / "example_script_transitions.json").read_text(encoding="utf-8")
    )
    script["scenes"][1]["transition_in"] = transition
    with pytest.raises(ValidationError):
        ScriptModel.model_validate(script)


def test_soft_push_defaults_feather_and_hard_push_rejects_it() -> None:
    script = json.loads(
        (SCRIPTS / "example_script_transitions.json").read_text(encoding="utf-8")
    )
    script["scenes"][1]["transition_in"] = {
        "type": "push",
        "direction": "left",
        "style": "soft",
        "duration_sec": 0.3,
    }
    model = ScriptModel.model_validate(script)
    transition = model.scenes[1].transition_in
    assert isinstance(transition, PushTransitionModel)
    assert transition.feather_frac == pytest.approx(0.03)

    script["scenes"][1]["transition_in"]["feather_frac"] = 0.03
    script["scenes"][1]["transition_in"]["style"] = "hard"
    with pytest.raises(ValidationError):
        ScriptModel.model_validate(script)


def test_first_scene_transition_must_be_null() -> None:
    script = json.loads(
        (SCRIPTS / "example_script.json").read_text(encoding="utf-8")
    )
    script["scenes"][0]["transition_in"] = {
        "type": "crossfade",
        "duration_sec": 0.3,
    }
    with pytest.raises(ValidationError, match="transition_in"):
        ScriptModel.model_validate(script)


def test_extra_duration_defaults_to_zero_and_accepts_positive_values() -> None:
    script = json.loads(
        (SCRIPTS / "example_script.json").read_text(encoding="utf-8")
    )
    script["scenes"][0].pop("extra_duration_sec", None)
    assert ScriptModel.model_validate(script).scenes[0].extra_duration_sec == 0.0
    script["scenes"][0]["extra_duration_sec"] = 2.0
    assert ScriptModel.model_validate(script).scenes[0].extra_duration_sec == 2.0


def test_extra_duration_rejects_negative_values() -> None:
    script = json.loads(
        (SCRIPTS / "example_script.json").read_text(encoding="utf-8")
    )
    script["scenes"][0]["extra_duration_sec"] = -0.1
    with pytest.raises(ValidationError):
        ScriptModel.model_validate(script)


def _asset_script(entry: object) -> dict:
    return {
        "project": {
            "title": "Asset validation",
            "aspect_ratio": "9:16",
            "resolution": [1080, 1920],
            "fps": 30,
            "voice_id": "voice",
        },
        "asset_registry": {"asset": entry},
        "scenes": [
            {
                "id": "scene_1",
                "bg": "asset",
                "narration_text": "Hello world",
                "transition_in": None,
            }
        ],
    }


def _generation(
    *,
    asset_type: str = "background",
    generation_method: str = "text_to_image",
    source_asset: str | None = None,
    transparent_background: bool | None = False,
) -> dict:
    return {
        "asset_type": asset_type,
        "generation_method": generation_method,
        "model": None,
        "description": "A generated test asset",
        "source_asset": source_asset,
        "transparent_background": transparent_background,
    }


def test_asset_registry_requires_object_entries() -> None:
    with pytest.raises(ValidationError):
        ScriptModel.model_validate(
            _asset_script("assets/backgrounds/example.jpg")
        )


def test_existing_asset_accepts_null_or_missing_generate(tmp_path: Path) -> None:
    asset = tmp_path / "assets" / "backgrounds" / "example.jpg"
    asset.parent.mkdir(parents=True)
    asset.write_bytes(b"asset")

    for entry in (
        {"path": "assets/backgrounds/example.jpg", "generate": None},
        {"path": "assets/backgrounds/example.jpg"},
    ):
        result = validate_script(_asset_script(entry), tmp_path / "assets")
        assert result.valid, result.errors


@pytest.mark.parametrize(
    "entry",
    [
        {"path": "assets/backgrounds/missing.jpg", "generate": None},
        {"path": "assets/backgrounds/missing.jpg"},
    ],
)
def test_missing_asset_without_generation_is_invalid(
    entry: dict,
    tmp_path: Path,
) -> None:
    result = validate_script(_asset_script(entry), tmp_path / "assets")
    assert not result.valid
    assert "file does not exist" in result.errors[0]
    assert "generation metadata" in result.errors[0]


def test_missing_or_existing_asset_with_valid_generation_is_valid(tmp_path: Path) -> None:
    entry = {
        "path": "assets/backgrounds/generated.jpg",
        "generate": _generation(),
    }
    missing_result = validate_script(_asset_script(entry), tmp_path / "assets")
    assert missing_result.valid, missing_result.errors

    path = tmp_path / "assets" / "backgrounds" / "generated.jpg"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"asset")
    existing_result = validate_script(_asset_script(entry), tmp_path / "assets")
    assert existing_result.valid, existing_result.errors


@pytest.mark.parametrize(
    "generation, expected",
    [
        ({}, "Field required"),
        (_generation(asset_type="invalid"), "Input should be"),
        (_generation(generation_method="invalid"), "Input should be"),
        (
            _generation(generation_method="text_to_image", source_asset="other"),
            "source_asset must be null",
        ),
        (
            _generation(generation_method="text_to_audio", source_asset="other"),
            "source_asset must be null",
        ),
        (
            _generation(generation_method="image_to_image"),
            "source_asset is required",
        ),
        (
            _generation(generation_method="audio_to_audio"),
            "source_asset is required",
        ),
        (
            _generation(
                generation_method="image_to_image",
                source_asset="assets/reference.png",
            ),
            "filesystem path",
        ),
        (
            _generation(
                generation_method="image_to_image",
                source_asset="missing",
            ),
            "not declared",
        ),
        (
            _generation(asset_type="background", transparent_background=None),
            "must be true or false",
        ),
        (
            _generation(asset_type="music", transparent_background=False),
            "must be null",
        ),
    ],
)
def test_generation_metadata_rules(
    generation: dict,
    expected: str,
    tmp_path: Path,
) -> None:
    entry = {
        "path": "assets/audio/generated.mp3",
        "generate": generation,
    }
    result = validate_script(_asset_script(entry), tmp_path / "assets")
    if generation == {}:
        with pytest.raises(ValidationError):
            ScriptModel.model_validate(_asset_script(entry))
        return
    assert not result.valid
    assert any(expected in error for error in result.errors)


def test_valid_source_asset_registry_keys_and_audio_transparency() -> None:
    script = _asset_script(
        {
            "path": "assets/audio/generated.mp3",
            "generate": _generation(
                asset_type="music",
                generation_method="audio_to_audio",
                source_asset="reference",
                transparent_background=None,
            ),
        }
    )
    script["asset_registry"]["reference"] = {
        "path": "assets/audio/reference.mp3",
        "generate": None,
    }
    result = validate_script(script, Path("/tmp/nonexistent-assets"))
    assert not result.valid
    assert all("source_asset" not in error for error in result.errors)


@pytest.mark.parametrize(
    "asset_type,generation_method,transparent_background",
    [
        ("background", "image_to_image", False),
        ("sprite", "image_to_image", True),
        ("sfx", "audio_to_audio", None),
        ("music", "audio_to_audio", None),
    ],
)
def test_valid_transformation_source_registry_keys(
    asset_type: str,
    generation_method: str,
    transparent_background: bool | None,
) -> None:
    script = _asset_script(
        {
            "path": f"assets/generated/{asset_type}",
            "generate": _generation(
                asset_type=asset_type,
                generation_method=generation_method,
                source_asset="reference",
                transparent_background=transparent_background,
            ),
        }
    )
    script["asset_registry"]["reference"] = {
        "path": "assets/reference/source",
        "generate": _generation(
            asset_type=asset_type,
            generation_method="text_to_image"
            if asset_type in {"background", "sprite"}
            else "text_to_audio",
            transparent_background=False
            if asset_type in {"background", "sprite"}
            else None,
        ),
    }
    result = validate_script(script, Path("/tmp/nonexistent-assets"))
    assert result.valid, result.errors


def test_asset_paths_resolve_from_shared_assets_root_not_script_directory(
    tmp_path: Path,
) -> None:
    shared = tmp_path / "assets" / "backgrounds" / "scene.jpg"
    shared.parent.mkdir(parents=True)
    shared.write_bytes(b"asset")
    script_dir = tmp_path / "scripts"
    script_dir.mkdir()
    result = validate_script(
        _asset_script({"path": "assets/backgrounds/scene.jpg"}),
        tmp_path / "assets",
    )
    assert result.valid, result.errors
