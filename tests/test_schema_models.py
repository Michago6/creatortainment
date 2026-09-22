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
SCRIPTS = ROOT / "scripts/example_scripts"


def test_all_example_scripts_load_as_typed_models() -> None:
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
