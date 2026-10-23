"""Pydantic-backed validation for authored Creatortainment scripts."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from .models import AssetRegistryEntryModel, ScriptModel
from .tokenize import spoken_words


@dataclass(frozen=True)
class ValidationResult:
    script: ScriptModel
    errors: list[str]

    @property
    def valid(self) -> bool:
        return not self.errors


class ScriptValidationError(ValueError):
    """A script validation failure retaining Pydantic's structured errors."""

    def __init__(self, path: Path, errors: list[dict[str, Any]]) -> None:
        self.path = path
        self.errors = errors
        super().__init__(f"Script {path} is invalid.")


@dataclass(frozen=True)
class AssetGenerationPlan:
    asset_key: str
    generation_method: str
    effective_model: str | None
    source_asset: str | None


def asset_generation_plans(script: ScriptModel) -> list[AssetGenerationPlan]:
    defaults = script.project.generation_defaults
    return [
        AssetGenerationPlan(
            asset_key=key,
            generation_method=entry.generate.generation_method,
            effective_model=(
                entry.generate.model
                if entry.generate.model is not None
                else defaults.get(entry.generate.generation_method)
            ),
            source_asset=entry.generate.source_asset,
        )
        for key, entry in script.asset_registry.items()
        if entry.generate is not None
    ]


def load_script(path: Path) -> ScriptModel:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValueError(f"Could not read script {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"Script {path} contains invalid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError("The script root must be a JSON object.")
    try:
        return ScriptModel.model_validate(value)
    except ValidationError as exc:
        raise ScriptValidationError(path, exc.errors()) from exc


def _index_error(path: str, index: Any, word_count: int) -> str | None:
    if not isinstance(index, int) or isinstance(index, bool):
        return f"{path} must be an integer."
    if index < 0 or index >= word_count:
        return f"{path}={index} is outside the scene's word range 0..{word_count - 1}."
    return None


def _asset_path(assets_root: Path, relative_path: str) -> Path:
    candidate = Path(relative_path)
    if (
        candidate.is_absolute()
        or ".." in candidate.parts
        or len(candidate.parts) < 2
        or candidate.parts[0] != "assets"
    ):
        raise ValueError(
            "asset_registry paths must be project-relative and begin with 'assets/'"
        )
    return assets_root.parent / candidate


def validate_script(
    script: ScriptModel | dict[str, Any],
    assets_root: Path,
) -> ValidationResult:
    """Validate typed shape plus the repository's semantic and asset rules."""
    errors: list[str] = []
    try:
        model = script if isinstance(script, ScriptModel) else ScriptModel.model_validate(script)
    except ValidationError as exc:
        return ValidationResult(
            script=script if isinstance(script, ScriptModel) else ScriptModel.model_construct(),
            errors=[error["msg"] for error in exc.errors()],
        )

    for key, entry in model.asset_registry.items():
        if not isinstance(key, str) or not key:
            errors.append("asset_registry keys must be non-empty strings.")
            continue
        if not isinstance(entry, AssetRegistryEntryModel):
            errors.append(f"asset_registry[{key!r}] must be an object with a path.")
            continue
        relative_path = entry.path
        try:
            path = _asset_path(assets_root, relative_path)
        except ValueError as exc:
            errors.append(f"asset_registry[{key!r}] {exc}.")
            continue
        generation = entry.generate
        if generation is None and not path.is_file():
            errors.append(
                f"asset_registry[{key!r}] file does not exist: {path}; "
                "the asset has no generation metadata and therefore needs a "
                "complete generate block if it is intended to be generated."
            )
        if generation is None:
            continue
        if generation.asset_type in {"background", "sprite"}:
            if generation.transparent_background is None:
                errors.append(
                    f"asset_registry[{key!r}].generate.transparent_background "
                    "must be true or false for image assets."
                )
        elif generation.transparent_background is not None:
            errors.append(
                f"asset_registry[{key!r}].generate.transparent_background "
                "must be null for audio assets."
            )
        if generation.generation_method in {"text_to_image", "text_to_audio"}:
            if generation.source_asset is not None:
                errors.append(
                    f"asset_registry[{key!r}].generate.source_asset must be null "
                    f"for {generation.generation_method}."
                )
        else:
            source = generation.source_asset
            if source is None:
                errors.append(
                    f"asset_registry[{key!r}].generate.source_asset is required "
                    f"for {generation.generation_method}."
                )
            else:
                source_path = Path(source)
                if (
                    source_path.is_absolute()
                    or "/" in source
                    or "\\" in source
                ):
                    errors.append(
                        f"asset_registry[{key!r}].generate.source_asset must be "
                        "an asset_registry key, not a filesystem path."
                    )
                elif source not in model.asset_registry:
                    errors.append(
                        f"asset_registry[{key!r}].generate.source_asset={source!r} "
                        "is not declared in asset_registry."
                    )

    try:
        effective_backgrounds = model.effective_backgrounds()
    except ValueError as exc:
        errors.append(str(exc))
        effective_backgrounds = [scene.bg for scene in model.scenes]

    for scene_number, (scene, effective_background) in enumerate(
        zip(model.scenes, effective_backgrounds),
        start=1,
    ):
        prefix = f"scenes[{scene_number - 1}]"
        scene_segments = scene.normalized_narration_segments(
            model.project.voice_id,
            scene_number - 1,
        )
        words = spoken_words(" ".join(segment.text for segment in scene_segments))
        if effective_background not in model.asset_registry:
            errors.append(
                f"{prefix}.bg={effective_background!r} is not declared in asset_registry."
            )
        music = scene.bg_music
        if music is not None:
            error = _index_error(
                f"{prefix}.bg_music.trigger_word_index",
                music.trigger_word_index,
                len(words),
            )
            if error:
                errors.append(error)
            if music.type == "start" and music.asset not in model.asset_registry:
                errors.append(
                    f"{prefix}.bg_music.asset={music.asset!r} is not declared in asset_registry."
                )
        for item_number, sfx in enumerate(scene.sfx):
            item_path = f"{prefix}.sfx[{item_number}]"
            if sfx.asset not in model.asset_registry:
                errors.append(
                    f"{item_path}.asset={sfx.asset!r} is not declared in asset_registry."
                )
            error = _index_error(
                f"{item_path}.trigger_word_index",
                sfx.trigger_word_index,
                len(words),
            )
            if error:
                errors.append(error)
        for element_number, element in enumerate(scene.elements):
            element_path = f"{prefix}.elements[{element_number}]"
            if element.asset not in model.asset_registry:
                errors.append(
                    f"{element_path}.asset={element.asset!r} is not declared in asset_registry."
                )
            for keyframe_number, keyframe in enumerate(element.keyframes):
                error = _index_error(
                    f"{element_path}.keyframes[{keyframe_number}].trigger_word_index",
                    keyframe.trigger_word_index,
                    len(words),
                )
                if error:
                    errors.append(error)
        camera = scene.camera
        if camera is not None:
            element_ids = [element.id for element in scene.elements]
            if len(element_ids) != len(set(element_ids)):
                errors.append(f"{prefix}.elements IDs must be unique for camera targeting.")
            previous_to = 0
            previous_mag = float(camera.initial_magnification)
            for move_number, move in enumerate(camera.moves):
                move_path = f"{prefix}.camera.moves[{move_number}]"
                if move.target_element_id not in element_ids:
                    errors.append(
                        f"{move_path}.target_element_id={move.target_element_id!r} "
                        "does not match a scene element id."
                    )
                if move.from_word_index < previous_to:
                    errors.append(f"{move_path} overlaps or is out of order.")
                if move.to_word_index < move.from_word_index:
                    errors.append(f"{move_path}.to_word_index must be >= from_word_index.")
                if move.to_word_index == move.from_word_index:
                    errors.append(f"{move_path} must span at least one spoken word.")
                if move.from_word_index >= len(words):
                    errors.append(
                        f"{move_path}.from_word_index={move.from_word_index} "
                        f"is outside the scene's word range 0..{len(words)}."
                    )
                if move.to_word_index > len(words):
                    errors.append(
                        f"{move_path}.to_word_index={move.to_word_index} "
                        f"cannot exceed word count {len(words)}."
                    )
                if abs(float(move.from_magnification) - previous_mag) > 1e-6:
                    errors.append(
                        f"{move_path}.from_magnification must continue the previous camera state."
                    )
                previous_to = move.to_word_index
                previous_mag = float(move.to_magnification)
    return ValidationResult(script=model, errors=errors)
