"""Generation planning and provider integration for script assets."""

from __future__ import annotations

import base64
import json
import mimetypes
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from . import config
from .schema.validate import AssetGenerationPlan, asset_generation_plans


class AssetGenerationError(RuntimeError):
    """Raised when an asset cannot be generated."""


@dataclass(frozen=True)
class GenerationRequest:
    asset_key: str
    model: str
    generation_method: str
    payload: dict
    output_path: Path


class GenerationProvider(Protocol):
    def generate(self, request: GenerationRequest) -> bytes:
        ...


def _data_uri(path: Path) -> str:
    content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{content_type};base64,{encoded}"


def build_generation_request(
    script,
    plan: AssetGenerationPlan,
    *,
    source_path: Path | None,
    output_path: Path,
) -> GenerationRequest:
    entry = script.asset_registry[plan.asset_key]
    generation = entry.generate
    assert generation is not None
    width, height = (int(value) for value in script.project.resolution)
    payload: dict
    if plan.generation_method == "text_to_image":
        payload = {
            "prompt": generation.description,
            "image_size": {"width": width, "height": height},
        }
    elif plan.generation_method == "image_to_image":
        if source_path is None:
            raise AssetGenerationError(
                f"{plan.asset_key}: source asset is unavailable."
            )
        payload = {
            "image_url": _data_uri(source_path),
            "image_size": {"width": width, "height": height},
        }
    elif plan.generation_method == "text_to_audio":
        payload = {"text_prompt": generation.description}
    elif plan.generation_method == "audio_to_audio":
        if source_path is None:
            raise AssetGenerationError(
                f"{plan.asset_key}: source asset is unavailable."
            )
        payload = {
            "prompt": generation.description,
            "audio_url": _data_uri(source_path),
        }
    else:  # pragma: no cover - Pydantic constrains this
        raise AssetGenerationError(
            f"{plan.asset_key}: unsupported generation method "
            f"{plan.generation_method!r}."
        )
    return GenerationRequest(
        asset_key=plan.asset_key,
        model=plan.effective_model or "",
        generation_method=plan.generation_method,
        payload=payload,
        output_path=output_path,
    )


def _find_output_url(value: object) -> str | None:
    if isinstance(value, dict):
        for key in ("url", "image_url", "audio_url"):
            candidate = value.get(key)
            if isinstance(candidate, str) and candidate.startswith(("http://", "https://")):
                return candidate
        for child in value.values():
            found = _find_output_url(child)
            if found:
                return found
    elif isinstance(value, list):
        for child in value:
            found = _find_output_url(child)
            if found:
                return found
    return None


class FalGenerationProvider:
    """Synchronous fal.ai model API adapter."""

    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = api_key or config.get_fal_key()

    def generate(self, request: GenerationRequest) -> bytes:
        url = f"https://fal.run/{request.model}"
        body = json.dumps(request.payload).encode("utf-8")
        http_request = Request(
            url,
            data=body,
            headers={
                "Authorization": f"Key {self.api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )
        try:
            with urlopen(http_request, timeout=600) as response:
                result = json.loads(response.read())
        except HTTPError as exc:
            raise AssetGenerationError(
                f"{request.asset_key}: fal.ai request failed (HTTP {exc.code})."
            ) from exc
        except (URLError, OSError) as exc:
            raise AssetGenerationError(
                f"{request.asset_key}: fal.ai request unavailable "
                f"({type(exc).__name__})."
            ) from exc
        except json.JSONDecodeError as exc:
            raise AssetGenerationError(
                f"{request.asset_key}: fal.ai returned invalid JSON."
            ) from exc

        output_url = _find_output_url(result)
        if output_url is None:
            raise AssetGenerationError(
                f"{request.asset_key}: fal.ai response did not contain an output file."
            )
        try:
            with urlopen(Request(output_url), timeout=300) as response:
                return response.read()
        except (HTTPError, URLError, OSError) as exc:
            raise AssetGenerationError(
                f"{request.asset_key}: could not download generated output "
                f"({type(exc).__name__})."
            ) from exc


def _asset_path(assets_root: Path, relative_path: str) -> Path:
    return assets_root.parent / relative_path


def _ordered_plans(script, assets_root: Path) -> list[AssetGenerationPlan]:
    plans = {plan.asset_key: plan for plan in asset_generation_plans(script)}
    visiting: set[str] = set()
    visited: set[str] = set()
    ordered: list[AssetGenerationPlan] = []

    def visit(key: str) -> None:
        if key in visited or key not in plans:
            return
        if key in visiting:
            raise AssetGenerationError(f"{key}: circular generation dependency.")
        visiting.add(key)
        source = plans[key].source_asset
        if source in plans:
            visit(source)
        visiting.remove(key)
        visited.add(key)
        ordered.append(plans[key])

    for key in plans:
        visit(key)
    return ordered


def generate_assets(
    script,
    assets_root: Path,
    *,
    force: bool = False,
    provider: GenerationProvider | None = None,
) -> tuple[list[str], list[str], list[str]]:
    provider = provider or FalGenerationProvider()
    generated: list[str] = []
    skipped: list[str] = []
    failed: list[str] = []
    for plan in _ordered_plans(script, assets_root):
        output_path = _asset_path(
            assets_root,
            script.asset_registry[plan.asset_key].path,
        )
        if output_path.is_file() and not force:
            skipped.append(plan.asset_key)
            continue
        source_path = None
        if plan.source_asset:
            source_entry = script.asset_registry.get(plan.source_asset)
            if source_entry is None:
                failed.append(f"{plan.asset_key}: source asset is not declared.")
                continue
            source_path = _asset_path(assets_root, source_entry.path)
            if not source_path.is_file():
                failed.append(
                    f"{plan.asset_key}: source asset file does not exist."
                )
                continue
        if not plan.effective_model:
            failed.append(f"{plan.asset_key}: no effective model configured.")
            continue
        try:
            request = build_generation_request(
                script,
                plan,
                source_path=source_path,
                output_path=output_path,
            )
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(provider.generate(request))
            generated.append(plan.asset_key)
        except (AssetGenerationError, OSError) as exc:
            failed.append(str(exc))
    return generated, skipped, failed
