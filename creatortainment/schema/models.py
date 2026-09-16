"""Pydantic schema primitives shared by authored script tooling."""

from __future__ import annotations

try:
    from pydantic import BaseModel, Field
except ImportError as exc:  # pragma: no cover - exercised only without full extras
    raise ImportError(
        "Pydantic is required for schema models. Install the project's full extras."
    ) from exc


class ProjectModel(BaseModel):
    """Project metadata, including the one model used for full-video narration."""

    title: str
    date: str | None = None
    aspect_ratio: str
    resolution: tuple[int, int]
    fps: int
    tts_model: str = Field(default="eleven_flash_v2_5", min_length=1)
    voice_id: str = Field(min_length=1)
