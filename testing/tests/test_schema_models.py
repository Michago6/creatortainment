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


ROOT = Path(__file__).parents[2]
SCRIPTS = ROOT / "testing/scripts"


def test_all_testing_scripts_load_as_typed_models() -> None:
    for path in sorted(SCRIPTS.glob("*.json")):
        model = load_script(path)
        result = validate_script(model, ROOT / "testing/assets")
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


def test_project_speed_defaults_to_one_and_accepts_inclusive_bounds() -> None:
    base = json.loads((SCRIPTS / "example_script.json").read_text(encoding="utf-8"))
    assert ScriptModel.model_validate(base).project.speed == 1.0
    for speed in (0.7, 1.2):
        candidate = json.loads(json.dumps(base))
        candidate["project"]["speed"] = speed
        assert ScriptModel.model_validate(candidate).project.speed == speed


def test_camera_moves_use_scene_local_spoken_word_ranges_and_element_ids() -> None:
    script = json.loads(
        (SCRIPTS / "example_script.json").read_text(encoding="utf-8")
    )
    scene = script["scenes"][0]
    scene["narration_text"] = "[whispers] " + scene["narration_text"]
    scene["camera"] = {
        "moves": [
            {
                "from_word_index": 0,
                "to_word_index": 2,
                "target_element_id": "main_character",
                "from_magnification": 1.0,
                "to_magnification": 1.4,
                "easing": "ease_in_out",
            },
            {
                "from_word_index": 2,
                "to_word_index": 4,
                "target_element_id": "gpu_diagram",
                "from_magnification": 1.4,
                "to_magnification": 1.8,
                "easing": "ease_out",
            },
        ]
    }
    result = validate_script(ScriptModel.model_validate(script), ROOT / "testing/assets")
    assert result.valid, result.errors


@pytest.mark.parametrize(
    "camera",
    [
        {
            "moves": [
                {
                    "from_word_index": 0,
                    "to_word_index": 2,
                    "target_element_id": "missing",
                    "from_magnification": 1.0,
                    "to_magnification": 1.2,
                }
            ]
        },
        {
            "moves": [
                {
                    "from_word_index": 2,
                    "to_word_index": 2,
                    "target_element_id": "main_character",
                    "from_magnification": 1.0,
                    "to_magnification": 1.2,
                }
            ]
        },
        {
            "moves": [
                {
                    "from_word_index": 0,
                    "to_word_index": 2,
                    "target_element_id": "main_character",
                    "from_magnification": 1.0,
                    "to_magnification": 1.2,
                },
                {
                    "from_word_index": 2,
                    "to_word_index": 4,
                    "target_element_id": "gpu_diagram",
                    "from_magnification": 1.1,
                    "to_magnification": 1.4,
                },
            ]
        },
    ],
)
def test_camera_moves_reject_invalid_targets_ranges_and_discontinuities(
    camera: dict,
) -> None:
    script = json.loads(
        (SCRIPTS / "example_script.json").read_text(encoding="utf-8")
    )
    script["scenes"][0]["camera"] = camera
    result = validate_script(
        ScriptModel.model_validate(script), ROOT / "testing/assets"
    )
    assert not result.valid


@pytest.mark.parametrize("speed", [0.69, 1.21, "fast", True])
def test_project_speed_rejects_invalid_values(speed) -> None:
    base = json.loads((SCRIPTS / "example_script.json").read_text(encoding="utf-8"))
    base["project"]["speed"] = speed
    with pytest.raises(ValidationError):
        ScriptModel.model_validate(base)


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


def test_backgrounds_inherit_until_explicitly_replaced() -> None:
    script = json.loads((SCRIPTS / "example_script.json").read_text(encoding="utf-8"))
    first_bg = script["scenes"][0]["bg"]
    second_bg = script["scenes"][-1]["bg"]
    for scene in script["scenes"][1:-1]:
        scene.pop("bg", None)
    script["scenes"][-1]["bg"] = second_bg

    model = ScriptModel.model_validate(script)

    assert model.effective_backgrounds() == [
        *([first_bg] * (len(script["scenes"]) - 1)),
        second_bg,
    ]


def test_first_scene_must_define_a_background() -> None:
    script = json.loads((SCRIPTS / "example_script.json").read_text(encoding="utf-8"))
    script["scenes"][0].pop("bg")

    with pytest.raises(ValidationError, match="no background has been defined"):
        ScriptModel.model_validate(script)


def test_legacy_narration_text_normalizes_to_one_default_voice_segment() -> None:
    script = json.loads(
        (SCRIPTS / "example_script.json").read_text(encoding="utf-8")
    )
    model = ScriptModel.model_validate(script)

    segments = model.normalized_narration_segments()
    assert segments[0].text == model.scenes[0].narration_text
    assert segments[0].voice_id == model.project.voice_id
    assert segments[0].id == f"{model.scenes[0].id}:segment-1"


def _multi_voice_script() -> dict:
    script = json.loads(
        (SCRIPTS / "example_script.json").read_text(encoding="utf-8")
    )
    script["scenes"] = [
        {
            "id": "dialogue_1",
            "bg": script["scenes"][0]["bg"],
            "narration_segments": [
                {"text": "Hello there.", "voice_id": "voice_a"},
                {"text": "Hi!", "voice_id": "voice_b"},
            ],
            "transition_in": None,
        },
        {
            "id": "dialogue_2",
            "bg": script["scenes"][1]["bg"],
            "narration_segments": [
                {"text": "Welcome back."},
                {"text": "Thanks.", "voice_id": "voice_b"},
            ],
            "transition_in": None,
        },
    ]
    return script


def test_multiple_voice_scenes_normalize_in_order_with_inherited_voice() -> None:
    script = _multi_voice_script()
    script["project"]["voice_id"] = "voice_default"
    model = ScriptModel.model_validate(script)

    segments = model.normalized_narration_segments()
    assert [(segment.scene_id, segment.text, segment.voice_id) for segment in segments] == [
        ("dialogue_1", "Hello there.", "voice_a"),
        ("dialogue_1", "Hi!", "voice_b"),
        ("dialogue_2", "Welcome back.", "voice_default"),
        ("dialogue_2", "Thanks.", "voice_b"),
    ]


def test_explicit_segment_ids_are_preserved_and_missing_ids_are_deterministic() -> None:
    script = _multi_voice_script()
    script["scenes"][0]["narration_segments"][0]["id"] = "opening-line"
    model = ScriptModel.model_validate(script)

    first = model.normalized_narration_segments()
    second = model.normalized_narration_segments()
    assert [segment.id for segment in first] == [
        "opening-line",
        "dialogue_1:segment-2",
        "dialogue_2:segment-1",
        "dialogue_2:segment-2",
    ]
    assert [segment.id for segment in first] == [segment.id for segment in second]


@pytest.mark.parametrize(
    "scene_update, expected",
    [
        (
            {"narration_text": "Hello.", "narration_segments": [{"text": "Hi."}]},
            "exactly one",
        ),
        ({"narration_text": "   "}, "non-empty"),
        ({"narration_segments": []}, "at least one"),
        ({"narration_segments": [{"text": "   "}]}, "non-empty"),
        ({"narration_segments": [{"text": "Hello.", "voice_id": ""}]}, "at least 1"),
    ],
)
def test_invalid_narration_definitions_are_rejected(
    scene_update: dict,
    expected: str,
) -> None:
    script = _multi_voice_script()
    scene = script["scenes"][0]
    scene.pop("narration_segments", None)
    scene.update(scene_update)
    with pytest.raises(ValidationError, match=expected):
        ScriptModel.model_validate(script)


def test_local_anchor_requires_valid_preceding_or_explicit_reference() -> None:
    script = _multi_voice_script()
    script["scenes"][0]["narration_segments"][1]["start_at_word"] = 1
    script["scenes"][0]["narration_segments"][1]["relative_to"] = "missing"
    with pytest.raises(ValidationError, match="unknown segment"):
        ScriptModel.model_validate(script)

    script["scenes"][0]["narration_segments"][1]["relative_to"] = "dialogue_1:segment-2"
    with pytest.raises(ValidationError, match="cannot reference itself"):
        ScriptModel.model_validate(script)


def test_first_segment_cannot_use_implicit_local_anchor() -> None:
    script = _multi_voice_script()
    script["scenes"][0]["narration_segments"][0]["start_at_word"] = 1
    with pytest.raises(ValidationError, match="without a preceding"):
        ScriptModel.model_validate(script)


def test_local_anchor_is_one_based() -> None:
    script = _multi_voice_script()
    script["scenes"][0]["narration_segments"][1]["start_at_word"] = 0
    with pytest.raises(ValidationError):
        ScriptModel.model_validate(script)


def test_empty_highlight_color_list_is_rejected() -> None:
    script = _multi_voice_script()
    script["project"]["caption_style"] = {"highlight_color": []}
    with pytest.raises(ValidationError, match="at least one"):
        ScriptModel.model_validate(script)


def test_duplicate_segment_ids_and_non_finite_offsets_are_rejected() -> None:
    script = _multi_voice_script()
    script["scenes"][1]["narration_segments"][0]["id"] = "dialogue_1:segment-1"
    with pytest.raises(ValidationError, match="IDs must be unique"):
        ScriptModel.model_validate(script)

    script = _multi_voice_script()
    script["scenes"][0]["narration_segments"][1]["start_offset_sec"] = float("nan")
    with pytest.raises(ValidationError, match="finite"):
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


@pytest.mark.parametrize("rotation", [0, 30, -30, 450])
def test_element_rotation_accepts_arbitrary_degrees(rotation: float) -> None:
    script = json.loads(
        (SCRIPTS / "example_script.json").read_text(encoding="utf-8")
    )
    script["scenes"][0]["elements"][0]["rotation"] = rotation
    model = ScriptModel.model_validate(script)
    assert model.scenes[0].elements[0].rotation == rotation


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
