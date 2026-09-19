"""Validation for authored Creatortainment scripts."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .tokenize import tokenize

VALID_ANCHORS = {"top_left", "center", "bottom_center"}


def _validate_caption_style(style: Any, path: str, errors: list[str]) -> None:
    if style is None:
        return
    if not isinstance(style, dict):
        errors.append(f"{path} must be an object or null.")
        return
    value = style.get("vertical_position_frac")
    if value is not None and (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not 0.0 <= value <= 1.0
    ):
        errors.append(f"{path}.vertical_position_frac must be between 0 and 1.")
    words_per_chunk = style.get("words_per_chunk")
    if words_per_chunk is not None and (
        isinstance(words_per_chunk, bool)
        or not isinstance(words_per_chunk, int)
        or words_per_chunk <= 0
    ):
        errors.append(f"{path}.words_per_chunk must be a positive integer.")


def _validate_duck_pct(value: Any, path: str, errors: list[str]) -> None:
    if value is not None and (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not 0.0 <= value <= 1.0
    ):
        errors.append(f"{path} must be between 0 and 1 or null.")


@dataclass(frozen=True)
class ValidationResult:
    script: dict[str, Any]
    errors: list[str]

    @property
    def valid(self) -> bool:
        return not self.errors


def load_script(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValueError(f"Could not read script {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"Script {path} contains invalid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError("The script root must be a JSON object.")
    return value


def _index_error(path: str, index: Any, word_count: int) -> str | None:
    if not isinstance(index, int) or isinstance(index, bool):
        return f"{path} must be an integer."
    if index < 0 or index >= word_count:
        return f"{path}={index} is outside the scene's word range 0..{word_count - 1}."
    return None


def validate_script(script: dict[str, Any], assets_root: Path) -> ValidationResult:
    errors: list[str] = []
    project = script.get("project")
    registry = script.get("asset_registry")
    scenes = script.get("scenes")

    if not isinstance(project, dict):
        errors.append("project must be an object.")
    elif (
        not isinstance(project.get("resolution"), list)
        or len(project["resolution"]) != 2
        or any(
            not isinstance(value, int) or isinstance(value, bool) or value <= 0
            for value in project["resolution"]
        )
    ):
        errors.append("project.resolution must be [positive_width, positive_height].")
    elif "tts_model" in project and (
        not isinstance(project["tts_model"], str) or not project["tts_model"].strip()
    ):
        errors.append("project.tts_model must be a non-empty string.")
    if isinstance(project, dict) and (
        not isinstance(project.get("voice_id"), str) or not project["voice_id"].strip()
    ):
        errors.append("project.voice_id must be a non-empty string.")
    if not isinstance(registry, dict):
        errors.append("asset_registry must be an object.")
        registry = {}
    if not isinstance(scenes, list) or not scenes:
        errors.append("scenes must be a non-empty array.")
        scenes = []
    if isinstance(project, dict):
        _validate_caption_style(project.get("caption_style"), "project.caption_style", errors)
        _validate_duck_pct(
            project.get("duck_to_narration_pct"),
            "project.duck_to_narration_pct",
            errors,
        )

    asset_paths: dict[str, Path] = {}
    for key, relative_path in registry.items():
        if not isinstance(key, str) or not key:
            errors.append("asset_registry keys must be non-empty strings.")
            continue
        if not isinstance(relative_path, str) or not relative_path.strip():
            errors.append(f"asset_registry[{key!r}] must be a non-empty relative path.")
            continue
        candidate = Path(relative_path)
        if candidate.is_absolute() or ".." in candidate.parts:
            errors.append(f"asset_registry[{key!r}] must stay inside the shared assets folder.")
            continue
        asset_paths[key] = assets_root / candidate.relative_to("assets") if candidate.parts and candidate.parts[0] == "assets" else assets_root / candidate
        if not asset_paths[key].is_file():
            errors.append(f"asset_registry[{key!r}] file does not exist: {asset_paths[key]}")

    if scenes and scenes[0].get("transition_in") is not None if isinstance(scenes[0], dict) else False:
        errors.append("scenes[0].transition_in must be null.")

    for scene_number, scene in enumerate(scenes, start=1):
        prefix = f"scenes[{scene_number - 1}]"
        if not isinstance(scene, dict):
            errors.append(f"{prefix} must be an object.")
            continue
        narration = scene.get("narration_text")
        if not isinstance(narration, str) or not narration.strip():
            errors.append(f"{prefix}.narration_text must be a non-empty string.")
            words: list[str] = []
        else:
            words = tokenize(narration)
        _validate_caption_style(
            scene.get("caption_style"),
            f"{prefix}.caption_style",
            errors,
        )
        _validate_duck_pct(
            scene.get("duck_to_narration_pct"),
            f"{prefix}.duck_to_narration_pct",
            errors,
        )

        def check_asset(field_path: str, key: Any) -> None:
            if not isinstance(key, str) or key not in registry:
                errors.append(f"{field_path}={key!r} is not declared in asset_registry.")

        check_asset(f"{prefix}.bg", scene.get("bg"))
        bg_music = scene.get("bg_music")
        if bg_music is not None:
            if not isinstance(bg_music, dict):
                errors.append(f"{prefix}.bg_music must be an object or null.")
            else:
                stop = bg_music.get("stop", False)
                if not isinstance(stop, bool):
                    errors.append(f"{prefix}.bg_music.stop must be a boolean.")
                if stop:
                    if "asset" in bg_music:
                        errors.append(f"{prefix}.bg_music.stop cues cannot specify asset.")
                else:
                    check_asset(f"{prefix}.bg_music.asset", bg_music.get("asset"))
                if "volume" in bg_music:
                    errors.append(f"{prefix}.bg_music no longer supports volume.")
                error = _index_error(
                    f"{prefix}.bg_music.trigger_word_index",
                    bg_music.get("trigger_word_index"),
                    len(words),
                )
                if error:
                    errors.append(error)

        sfx_items = scene.get("sfx", [])
        if not isinstance(sfx_items, list):
            errors.append(f"{prefix}.sfx must be an array.")
            sfx_items = []
        for item_number, sfx in enumerate(sfx_items):
            item_path = f"{prefix}.sfx[{item_number}]"
            if not isinstance(sfx, dict):
                errors.append(f"{item_path} must be an object.")
                continue
            check_asset(f"{item_path}.asset", sfx.get("asset"))
            error = _index_error(
                f"{item_path}.trigger_word_index",
                sfx.get("trigger_word_index"),
                len(words),
            )
            if error:
                errors.append(error)

        elements = scene.get("elements", [])
        if not isinstance(elements, list):
            errors.append(f"{prefix}.elements must be an array.")
            elements = []
        for element_number, element in enumerate(elements):
            element_path = f"{prefix}.elements[{element_number}]"
            if not isinstance(element, dict):
                errors.append(f"{element_path} must be an object.")
                continue
            check_asset(f"{element_path}.asset", element.get("asset"))
            anchor = element.get("anchor")
            if anchor not in VALID_ANCHORS:
                errors.append(
                    f"{element_path}.anchor must be one of {sorted(VALID_ANCHORS)}."
                )
            keyframes = element.get("keyframes", [])
            if not isinstance(keyframes, list) or not keyframes:
                errors.append(f"{element_path}.keyframes must be a non-empty array.")
                continue
            for keyframe_number, keyframe in enumerate(keyframes):
                if not isinstance(keyframe, dict):
                    errors.append(f"{element_path}.keyframes[{keyframe_number}] must be an object.")
                    continue
                keyframe_path = f"{element_path}.keyframes[{keyframe_number}]"
                has_height = "target_height_frac" in keyframe
                has_width = "target_width_frac" in keyframe
                stretch = keyframe.get("stretch", False) is True
                if not has_height and not has_width:
                    errors.append(
                        f"{keyframe_path} must define target_height_frac or target_width_frac."
                    )
                if has_height and has_width and not stretch:
                    errors.append(
                        f"{keyframe_path} cannot define both target dimensions without stretch=true."
                    )
                for field_name in ("target_height_frac", "target_width_frac"):
                    value = keyframe.get(field_name)
                    if field_name in keyframe and (
                        not isinstance(value, (int, float))
                        or isinstance(value, bool)
                        or not 0.0 <= value <= 1.0
                    ):
                        errors.append(f"{keyframe_path}.{field_name} must be between 0 and 1.")
                if "pos" not in keyframe or (
                    not isinstance(keyframe.get("pos"), list)
                    or len(keyframe["pos"]) != 2
                    or any(not isinstance(value, (int, float)) for value in keyframe["pos"])
                ):
                    errors.append(f"{keyframe_path}.pos must be [x, y] numbers.")
                error = _index_error(
                    f"{keyframe_path}.trigger_word_index",
                    keyframe.get("trigger_word_index"),
                    len(words),
                )
                if error:
                    errors.append(error)

    return ValidationResult(script=script, errors=errors)
