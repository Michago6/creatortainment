"""Typed Pydantic models for authored Creatortainment scripts."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Annotated, Any, Literal

try:
    from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
except ImportError as exc:  # pragma: no cover
    raise ImportError(
        "Pydantic is required for schema models. Install the project's full extras."
    ) from exc


class ScriptModelBase(BaseModel):
    """Typed model with temporary mapping compatibility for render consumers."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    def __getitem__(self, key: str) -> Any:
        return getattr(self, key)

    def __setitem__(self, key: str, value: Any) -> None:
        setattr(self, key, value)

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)

    def __contains__(self, key: str) -> bool:
        if key in type(self).model_fields:
            return getattr(self, key) is not None
        extra = getattr(self, "__pydantic_extra__", None) or {}
        return key in extra

    def keys(self):
        return self.model_dump(exclude_none=True).keys()

    def items(self):
        return self.model_dump(exclude_none=True).items()


class CaptionStyleModel(ScriptModelBase):
    font: str | None = None
    font_size: int | None = None
    color: str | None = None
    stroke_color: str | None = None
    stroke_width: int | None = None
    position: Literal["top_left", "center", "bottom_center"] | None = None
    max_chars_per_line: int | None = None
    highlight_color: str | list[str] | None = None
    highlight_scale: float | None = None
    words_per_chunk: int | None = Field(default=None, gt=0)
    vertical_position_frac: float | None = Field(default=None, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def validate_highlight_colors(self) -> "CaptionStyleModel":
        if isinstance(self.highlight_color, list) and not self.highlight_color:
            raise ValueError("highlight_color must contain at least one color")
        return self


class KeyframeModel(ScriptModelBase):
    trigger_word_index: int
    pos: tuple[float, float]
    target_height_frac: float | None = Field(default=None, ge=0.0, le=1.0)
    target_width_frac: float | None = Field(default=None, ge=0.0, le=1.0)
    opacity: float | None = Field(default=None, ge=0.0, le=1.0)
    easing: str | None = None
    stretch: bool = False

    @model_validator(mode="after")
    def validate_target_dimensions(self) -> "KeyframeModel":
        if self.target_height_frac is None and self.target_width_frac is None:
            raise ValueError(
                "a keyframe must define target_height_frac or target_width_frac"
            )
        if (
            self.target_height_frac is not None
            and self.target_width_frac is not None
            and not self.stretch
        ):
            raise ValueError(
                "a keyframe cannot define both target dimensions without stretch=true"
            )
        return self


class ElementModel(ScriptModelBase):
    id: str
    asset: str
    rotation: float = 0.0
    z_index: int = 0
    anchor: Literal["top_left", "center", "bottom_center"]
    keyframes: list[KeyframeModel] = Field(min_length=1)


class SfxCueModel(ScriptModelBase):
    asset: str
    trigger_word_index: int
    volume: float = 1.0


class BgMusicStartModel(ScriptModelBase):
    type: Literal["start"] = "start"
    asset: str
    trigger_word_index: int
    fade_in_sec: float = Field(default=0.0, ge=0.0)


class BgMusicStopModel(ScriptModelBase):
    type: Literal["stop"] = "stop"
    stop: Literal[True] = True
    trigger_word_index: int
    fade_in_sec: float = Field(default=0.0, ge=0.0)


BgMusicModel = Annotated[
    BgMusicStartModel | BgMusicStopModel,
    Field(discriminator="type"),
]


class CrossfadeTransitionModel(ScriptModelBase):
    type: Literal["crossfade"]
    duration_sec: float = Field(gt=0.0)


class ZoomOutTransitionModel(ScriptModelBase):
    type: Literal["zoom_out"]
    duration_sec: float = Field(gt=0.0)
    zoom_scale: float = Field(default=1.3, gt=1.0)


class PushTransitionModel(ScriptModelBase):
    type: Literal["push"]
    direction: Literal["left", "right"]
    style: Literal["hard", "soft"]
    duration_sec: float = Field(gt=0.0)
    feather_frac: float | None = Field(default=None, gt=0.0, lt=0.5)

    @model_validator(mode="after")
    def validate_feather(self) -> "PushTransitionModel":
        if self.style == "soft" and self.feather_frac is None:
            self.feather_frac = 0.03
        if self.style == "hard" and self.feather_frac is not None:
            raise ValueError("feather_frac is only valid for soft push transitions")
        return self


TransitionInModel = Annotated[
    CrossfadeTransitionModel | ZoomOutTransitionModel | PushTransitionModel,
    Field(discriminator="type"),
]


class AssetGenerationModel(ScriptModelBase):
    asset_type: Literal["background", "sprite", "sfx", "music"]
    generation_method: Literal[
        "text_to_image",
        "image_to_image",
        "text_to_audio",
        "audio_to_audio",
    ]
    model: str | None = None
    description: str = Field(min_length=1)
    source_asset: str | None = None
    transparent_background: bool | None = None


class AssetRegistryEntryModel(ScriptModelBase):
    path: str = Field(min_length=1)
    generate: AssetGenerationModel | None = None


class NarrationSegmentModel(ScriptModelBase):
    id: str | None = Field(default=None, min_length=1)
    text: str = Field(min_length=1)
    voice_id: str | None = Field(default=None, min_length=1)
    relative_to: str | None = Field(default=None, min_length=1)
    start_at_word: int | None = Field(default=None, ge=1)
    start_offset_sec: float = 0.0

    @model_validator(mode="after")
    def validate_text(self) -> "NarrationSegmentModel":
        if not self.text.strip():
            raise ValueError("narration segment text must be a non-empty string")
        if self.voice_id is not None and not self.voice_id.strip():
            raise ValueError("narration segment voice_id must be a non-empty string")
        if not math.isfinite(self.start_offset_sec):
            raise ValueError("narration segment start_offset_sec must be finite")
        if self.start_at_word is None and self.relative_to is not None:
            raise ValueError("relative_to requires start_at_word")
        return self


@dataclass(frozen=True)
class NarrationSegment:
    id: str
    scene_id: str
    text: str
    voice_id: str
    scene_index: int
    segment_index: int
    relative_to: str | None = None
    start_at_word: int | None = None
    start_offset_sec: float = 0.0


class ProjectModel(ScriptModelBase):
    title: str
    date: str | None = None
    aspect_ratio: str
    resolution: tuple[int, int]
    fps: int
    tts_model: str = Field(default="eleven_flash_v2_5", min_length=1)
    voice_id: str = Field(min_length=1)
    speed: float = Field(default=1.0, ge=0.7, le=1.2)
    generation_defaults: dict[
        Literal["text_to_image", "image_to_image", "text_to_audio", "audio_to_audio"],
        str | None,
    ] = Field(default_factory=dict)
    duck_to_narration_pct: float = Field(default=0.3, gt=0.0, le=1.0)
    caption_style: CaptionStyleModel | None = None

    @model_validator(mode="after")
    def validate_voice_id(self) -> "ProjectModel":
        if not self.voice_id.strip():
            raise ValueError("project voice_id must be a non-empty string")
        return self

    @field_validator("speed", mode="before")
    @classmethod
    def validate_speed_type(cls, value: Any) -> Any:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("project speed must be a number between 0.7 and 1.2")
        if not math.isfinite(float(value)):
            raise ValueError("project speed must be a finite number between 0.7 and 1.2")
        return value


class SceneModel(ScriptModelBase):
    id: str
    bg: str | None = None
    narration_text: str | None = None
    narration_segments: list[NarrationSegmentModel] | None = None
    caption_style: CaptionStyleModel | None = None
    duration_sec: None = None
    extra_duration_sec: float = Field(default=0.0, ge=0.0)
    pause_before_sec: float = Field(default=0.3, ge=0.0)
    transition_in: TransitionInModel | None = None
    duck_to_narration_pct: float | None = Field(default=None, gt=0.0, le=1.0)
    bg_music: BgMusicModel | None = None
    sfx: list[SfxCueModel] = Field(default_factory=list)
    elements: list[ElementModel] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_narration_definition(self) -> "SceneModel":
        has_text = self.narration_text is not None
        has_segments = self.narration_segments is not None
        if has_text == has_segments:
            raise ValueError(
                "a scene must define exactly one of narration_text or narration_segments"
            )
        if has_text and not self.narration_text.strip():
            raise ValueError("narration_text must be a non-empty string")
        if has_segments and not self.narration_segments:
            raise ValueError("narration_segments must contain at least one segment")
        return self

    def normalized_narration_segments(
        self,
        default_voice_id: str,
        scene_index: int,
    ) -> list[NarrationSegment]:
        if self.narration_text is not None:
            return [
                NarrationSegment(
                    id=f"{self.id}:segment-1",
                    scene_id=self.id,
                    text=self.narration_text,
                    voice_id=default_voice_id,
                    scene_index=scene_index,
                    segment_index=0,
                )
            ]
        assert self.narration_segments is not None
        return [
            NarrationSegment(
                id=segment.id or f"{self.id}:segment-{segment_index + 1}",
                scene_id=self.id,
                text=segment.text,
                voice_id=segment.voice_id or default_voice_id,
                scene_index=scene_index,
                segment_index=segment_index,
                relative_to=segment.relative_to,
                start_at_word=segment.start_at_word,
                start_offset_sec=segment.start_offset_sec,
            )
            for segment_index, segment in enumerate(self.narration_segments)
        ]


class ScriptModel(ScriptModelBase):
    conventions: dict[str, Any] = Field(default_factory=dict, alias="_conventions")
    project: ProjectModel
    asset_registry: dict[str, AssetRegistryEntryModel]
    scenes: list[SceneModel] = Field(min_length=1)

    def effective_backgrounds(self) -> list[str]:
        """Resolve each scene's background through forward inheritance."""
        backgrounds: list[str] = []
        active: str | None = None
        for index, scene in enumerate(self.scenes):
            if scene.bg is not None:
                active = scene.bg
            elif active is None:
                raise ValueError(
                    f"scenes[{index}].bg is required because no background has been defined yet"
                )
            assert active is not None
            backgrounds.append(active)
        return backgrounds

    @model_validator(mode="before")
    @classmethod
    def tag_legacy_music_cues(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        copied = dict(value)
        scenes = []
        for scene in copied.get("scenes", []):
            if not isinstance(scene, dict):
                scenes.append(scene)
                continue
            scene_copy = dict(scene)
            music = scene_copy.get("bg_music")
            if isinstance(music, dict) and "type" not in music:
                music_copy = dict(music)
                music_copy["type"] = "stop" if music_copy.get("stop") is True else "start"
                scene_copy["bg_music"] = music_copy
            scenes.append(scene_copy)
        copied["scenes"] = scenes
        return copied

    @model_validator(mode="after")
    def validate_scene_order(self) -> "ScriptModel":
        if self.scenes[0].transition_in is not None:
            raise ValueError("scenes[0].transition_in must be null")
        self.effective_backgrounds()
        self.normalized_narration_segments()
        segments = self.normalized_narration_segments()
        by_id = {segment.id: segment for segment in segments}
        for index, segment in enumerate(segments):
            if segment.start_at_word is None:
                continue
            reference_id = segment.relative_to
            if reference_id is None:
                if segment.segment_index == 0:
                    raise ValueError(
                        f"narration segment {segment.id!r} cannot anchor without a preceding segment"
                    )
                reference_id = next(
                    item.id
                    for item in segments
                    if item.scene_id == segment.scene_id
                    and item.segment_index == segment.segment_index - 1
                )
                if by_id[reference_id].scene_id != segment.scene_id:
                    raise ValueError(
                        f"narration segment {segment.id!r} has an invalid implicit anchor"
                    )
            reference = by_id.get(reference_id)
            if reference is None:
                raise ValueError(
                    f"narration segment {segment.id!r} references unknown segment {reference_id!r}"
                )
            if reference.id == segment.id:
                raise ValueError(
                    f"narration segment {segment.id!r} cannot reference itself"
                )
            if segments.index(reference) >= index:
                raise ValueError(
                    f"narration segment {segment.id!r} must reference a preceding segment"
                )
        return self

    def normalized_narration_segments(self) -> list[NarrationSegment]:
        segments: list[NarrationSegment] = []
        segment_ids: set[str] = set()
        for scene_index, scene in enumerate(self.scenes):
            scene_segments = scene.normalized_narration_segments(
                self.project.voice_id,
                scene_index,
            )
            duplicate_ids = {
                segment.id for segment in scene_segments if segment.id in segment_ids
            }
            if duplicate_ids:
                raise ValueError(
                    "narration segment IDs must be unique: "
                    + ", ".join(sorted(duplicate_ids))
                )
            segment_ids.update(segment.id for segment in scene_segments)
            segments.extend(
                scene_segments
            )
        return segments
