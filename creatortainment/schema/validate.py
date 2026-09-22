"""Pydantic-backed validation for authored Creatortainment scripts."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from .models import AssetRegistryEntryModel, ScriptModel
from .tokenize import tokenize


@dataclass(frozen=True)
class ValidationResult:
    script: ScriptModel
    errors: list[str]

    @property
    def valid(self) -> bool:
        return not self.errors


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
        messages = "; ".join(error["msg"] for error in exc.errors())
        raise ValueError(f"Script {path} is invalid: {messages}") from exc


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

    for scene_number, scene in enumerate(model.scenes, start=1):
        prefix = f"scenes[{scene_number - 1}]"
        words = tokenize(scene.narration_text)
        if not scene.narration_text.strip():
            errors.append(f"{prefix}.narration_text must be a non-empty string.")
        if scene.bg not in model.asset_registry:
            errors.append(f"{prefix}.bg={scene.bg!r} is not declared in asset_registry.")
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
    return ValidationResult(script=model, errors=errors)
