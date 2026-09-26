"""Typed Pydantic models for authored Creatortainment scripts."""

from __future__ import annotations

from typing import Annotated, Any, Literal

try:
    from pydantic import BaseModel, ConfigDict, Field, model_validator
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
    highlight_color: str | None = None
    highlight_scale: float | None = None
    words_per_chunk: int | None = Field(default=None, gt=0)
    vertical_position_frac: float | None = Field(default=None, ge=0.0, le=1.0)


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


class ProjectModel(ScriptModelBase):
    title: str
    date: str | None = None
    aspect_ratio: str
    resolution: tuple[int, int]
    fps: int
    tts_model: str = Field(default="eleven_flash_v2_5", min_length=1)
    voice_id: str = Field(min_length=1)
    generation_defaults: dict[
        Literal["text_to_image", "image_to_image", "text_to_audio", "audio_to_audio"],
        str | None,
    ] = Field(default_factory=dict)
    duck_to_narration_pct: float = Field(default=0.3, gt=0.0, le=1.0)
    caption_style: CaptionStyleModel | None = None


class SceneModel(ScriptModelBase):
    id: str
    bg: str
    narration_text: str
    caption_style: CaptionStyleModel | None = None
    duration_sec: None = None
    extra_duration_sec: float = Field(default=0.0, ge=0.0)
    pause_before_sec: float = Field(default=0.3, ge=0.0)
    transition_in: TransitionInModel | None = None
    duck_to_narration_pct: float | None = Field(default=None, gt=0.0, le=1.0)
    bg_music: BgMusicModel | None = None
    sfx: list[SfxCueModel] = Field(default_factory=list)
    elements: list[ElementModel] = Field(default_factory=list)


class ScriptModel(ScriptModelBase):
    conventions: dict[str, Any] = Field(default_factory=dict, alias="_conventions")
    project: ProjectModel
    asset_registry: dict[str, AssetRegistryEntryModel]
    scenes: list[SceneModel] = Field(min_length=1)

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
        return self
