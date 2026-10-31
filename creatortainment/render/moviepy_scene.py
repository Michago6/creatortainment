"""MoviePy 2.x static scene composition for the first video checkpoint."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
from moviepy import (
    AudioFileClip,
    AudioClip,
    CompositeAudioClip,
    CompositeVideoClip,
    ImageClip,
    TextClip,
    VideoClip,
    concatenate_videoclips,
    vfx,
)
from PIL import Image, ImageFont

from .captions import (
    CaptionImageCache,
    caption_position,
    highlight_color_for_voice,
    resolve_active_caption,
    resolve_active_caption_track,
    wrap_caption_lines,
)
from ..audio.mixing import build_final_audio_mix
from ..audio.manifest import validate_audio_timing
from ..audio.tokenize import spoken_words
from .mock import AssetDimensionCache, _asset_path
from .visual_assets import is_animated_visual, load_visual_clip
from .keyframes import resolve_element_state
from .text_elements import text_element_image
from .timeline import build_scene_final_offsets, scene_duration_sec
from ..timeline import timed_element

SOFT_PUSH_FEATHER_FRAC = 0.25


def _camera_value(value: Any, key: str, default: Any = None) -> Any:
    return value.get(key, default) if isinstance(value, dict) else getattr(value, key, default)


def _camera_clip(
    content: VideoClip,
    scene: dict[str, Any],
    scene_manifest: dict[str, Any],
    manifest: dict[str, Any],
    resolution: tuple[int, int],
) -> VideoClip:
    """Apply a scene camera to composited visual layers (captions are added later)."""
    camera = _camera_value(scene, "camera")
    moves = _camera_value(camera, "moves", []) if camera is not None else []
    if not moves:
        return content
    timestamps = manifest.get("word_timestamps", [])
    word_offset = int(scene_manifest.get("word_offset", 0))
    scene_start = float(scene_manifest["start_time_sec"])
    scene_end = float(scene_manifest["end_time_sec"])
    duration = float(content.duration)
    elements = scene.get("elements", [])
    by_id = {
        str(_camera_value(element, "id")): element
        for element in elements
    }
    cache = AssetDimensionCache()
    registry = manifest.get("_asset_registry", {})
    assets_root = manifest.get("_assets_root")

    def move_times(move: Any) -> tuple[float, float]:
        first = int(_camera_value(move, "from_word_index"))
        last = int(_camera_value(move, "to_word_index"))
        start = (
            float(timestamps[word_offset + first]["start"])
            if word_offset + first < len(timestamps)
            else scene_start
        )
        end = (
            float(timestamps[word_offset + last]["start"])
            if word_offset + last < len(timestamps)
            else scene_end
        )
        return max(scene_start, start), min(scene_end, max(start, end))

    intervals = [(move, *move_times(move)) for move in moves]
    canvas_width, canvas_height = resolution
    initial_center = (canvas_width / 2.0, canvas_height / 2.0)
    def target_center(move: Any, absolute_time: float) -> tuple[float, float]:
        element = by_id.get(str(_camera_value(move, "target_element_id")))
        if element is None:
            return initial_center
        try:
            timed = timed_element(element, scene, scene_manifest, manifest)
            state = resolve_element_state(timed, absolute_time)
            x, y = (float(state["pos"][0]), float(state["pos"][1]))
            element_width = element_height = 0.0
            if _camera_value(element, "text") is not None:
                text_width, text_height = text_element_image(element).size
                native_width, native_height = text_width, text_height
            elif assets_root is not None:
                path = _asset_path(registry, _camera_value(element, "asset"), assets_root)
                native_width, native_height = cache.dimensions(path)
            else:
                return initial_center
            if state["size_field_name"] == "target_height_frac":
                element_height = state["size_value"] * canvas_height
                element_width = native_width * element_height / max(1, native_height)
            else:
                element_width = state["size_value"] * canvas_width
                element_height = native_height * element_width / max(1, native_width)
            anchor = _camera_value(element, "anchor", "center")
            if anchor == "top_left":
                return (x + element_width / 2, y + element_height / 2)
            if anchor == "bottom_center":
                return (x, y - element_height / 2)
            return (x, y)
        except (KeyError, ValueError, TypeError):
            return initial_center

    def camera_state(absolute: float) -> tuple[tuple[float, float], float]:
        center = initial_center
        magnification = 1.0
        for move, start, end in intervals:
            if absolute < start:
                break
            from_mag = float(_camera_value(move, "from_magnification"))
            to_mag = float(_camera_value(move, "to_magnification"))
            if absolute >= end:
                center = target_center(move, end)
                magnification = to_mag
                continue
            span = max(1e-9, end - start)
            raw = max(0.0, min(1.0, (absolute - start) / span))
            easing = str(_camera_value(move, "easing", "linear"))
            from .keyframes import EASINGS
            progress = EASINGS[easing](raw)
            destination = target_center(move, absolute)
            center = (
                center[0] + (destination[0] - center[0]) * progress,
                center[1] + (destination[1] - center[1]) * progress,
            )
            magnification = from_mag + (to_mag - from_mag) * progress
            break
        return center, magnification

    def frame(local_time: float) -> np.ndarray:
        absolute = scene_start + float(local_time)
        center, magnification = camera_state(absolute)
        source = Image.fromarray(content.get_frame(local_time)).convert("RGB")
        if magnification <= 1.000001:
            return np.asarray(source)
        scaled = source.resize(
            (max(canvas_width, round(canvas_width * magnification)), max(canvas_height, round(canvas_height * magnification))),
            Image.Resampling.LANCZOS,
        )
        cx, cy = center[0] * magnification, center[1] * magnification
        left = max(0, min(scaled.width - canvas_width, round(cx - canvas_width / 2)))
        top = max(0, min(scaled.height - canvas_height, round(cy - canvas_height / 2)))
        return np.asarray(scaled.crop((left, top, left + canvas_width, top + canvas_height)))

    return VideoClip(frame_function=frame, duration=duration)


def effective_backgrounds(script: dict[str, Any]) -> list[str]:
    """Resolve explicit and inherited scene background registry keys."""
    resolver = getattr(script, "effective_backgrounds", None)
    if callable(resolver):
        return resolver()
    backgrounds: list[str] = []
    active: str | None = None
    for index, scene in enumerate(script.get("scenes", [])):
        value = scene.get("bg")
        if value is not None:
            active = value
        elif active is None:
            raise ValueError(
                f"scenes[{index}].bg is required because no background has been defined yet"
            )
        backgrounds.append(active)
    return backgrounds


class BackgroundTimeline:
    """Share one continuously advancing source clip across a background run."""

    def __init__(
        self,
        path: Path,
        resolution: tuple[int, int],
        duration: float,
    ) -> None:
        self.source = _cover_background(path, resolution, duration)
        self.duration = duration

    def clip(self, offset_sec: float, duration: float) -> VideoClip:
        start = max(0.0, float(offset_sec))
        end = min(self.duration, start + duration)
        if end <= start:
            raise ValueError("Background timeline requested an empty source range.")
        return self.source.subclipped(start, end).with_duration(duration)

    def close(self) -> None:
        self.source.close()


def _cover_background(path: Path, resolution: tuple[int, int], duration: float) -> VideoClip:
    width, height = resolution
    clip = load_visual_clip(path, duration)
    scale = max(width / clip.w, height / clip.h)
    resized = clip.resized(new_size=(round(clip.w * scale), round(clip.h * scale)))
    return resized.cropped(
        x_center=resized.w / 2,
        y_center=resized.h / 2,
        width=width,
        height=height,
    ).with_duration(duration)


def _background_runs(
    script: dict[str, Any],
    backgrounds: list[str],
    scene_offsets: list[Any],
) -> list[tuple[int, int, str, float, float]]:
    runs: list[tuple[int, int, str, float, float]] = []
    start = 0
    for index in range(1, len(backgrounds) + 1):
        if index == len(backgrounds) or backgrounds[index] != backgrounds[start]:
            origin = float(scene_offsets[start].visual_start_sec)
            end = max(
                float(scene_offsets[item].visual_start_sec)
                + float(scene_offsets[item].unit_duration_sec)
                for item in range(start, index)
            )
            runs.append((start, index, backgrounds[start], origin, end))
            start = index
    return runs


def _element_clip(
    element: dict[str, Any],
    registry: dict[str, Any],
    assets_root: Path,
    resolution: tuple[int, int],
    duration: float,
    dimension_cache: AssetDimensionCache,
) -> VideoClip:
    if element.get("text") is not None:
        text_image = text_element_image(element)
        native_width, native_height = text_image.size
        image = ImageClip(np.asarray(text_image), transparent=True).with_duration(duration)
    else:
        path = _asset_path(registry, element["asset"], assets_root)
        image = load_visual_clip(path, duration)
        native_width, native_height = dimension_cache.dimensions(path)
    keyframe = element["keyframes"][0]
    target_height = keyframe.get("target_height_frac")
    target_width = keyframe.get("target_width_frac")
    if target_height is not None and target_width is not None and keyframe.get("stretch") is True:
        size = (
            max(1, round(float(target_width) * resolution[0])),
            max(1, round(float(target_height) * resolution[1])),
        )
        image = image.resized(new_size=size)
    elif target_height is not None:
        image = image.resized(height=max(1, round(float(target_height) * resolution[1])))
    elif target_width is not None:
        image = image.resized(width=max(1, round(float(target_width) * resolution[0])))
    else:
        raise ValueError(f"Element {element.get('id', '<unnamed>')} has no target size.")

    rotation = float(element.get("rotation", 0.0))
    if rotation:
        image = image.rotated(rotation, expand=True)
    opacity = float(keyframe.get("opacity", 1.0))
    if opacity != 1.0:
        image = image.with_opacity(opacity)
    x, y = keyframe["pos"]
    anchor = element["anchor"]
    if anchor == "top_left":
        position = (round(x), round(y))
    elif anchor == "bottom_center":
        position = (round(x - image.w / 2), round(y - image.h))
    else:
        position = (round(x - image.w / 2), round(y - image.h / 2))
    return image.with_position(position).with_duration(duration)


def _anchor_position(
    anchor: str,
    x: float,
    y: float,
    width: int,
    height: int,
) -> tuple[int, int]:
    """Convert an element anchor point to its MoviePy top-left position."""
    if anchor == "top_left":
        return round(x), round(y)
    if anchor == "bottom_center":
        return round(x - width / 2), round(y - height)
    return round(x - width / 2), round(y - height / 2)


def _animated_element_clip(
    element: dict[str, Any],
    scene: dict[str, Any],
    scene_manifest: dict[str, Any],
    manifest: dict[str, Any],
    registry: dict[str, Any],
    assets_root: Path,
    resolution: tuple[int, int],
    duration: float,
    dimension_cache: AssetDimensionCache,
) -> VideoClip:
    """Create a cropped dynamic clip driven by resolved element states."""
    if element.get("text") is not None:
        path = None
        source_clip = None
        source = text_element_image(element)
        native_width, native_height = source.size
    else:
        path = _asset_path(registry, element["asset"], assets_root)
        source_clip = load_visual_clip(path, duration) if is_animated_visual(path) else None
        if source_clip is None:
            with Image.open(path) as image_file:
                source = image_file.convert("RGBA")
        else:
            source = None
    timed = timed_element(element, scene, scene_manifest, manifest)
    canvas_width, canvas_height = resolution
    if path is not None:
        native_width, native_height = dimension_cache.dimensions(path)
    cached_time: float | None = None
    cached_frame: Image.Image | None = None
    cached_position: tuple[int, int] = (0, 0)

    def render_element(local_time: float) -> Image.Image:
        nonlocal cached_time, cached_frame, cached_position
        if cached_time == local_time and cached_frame is not None:
            return cached_frame
        absolute_time = float(scene_manifest["start_time_sec"]) + local_time
        state = resolve_element_state(timed, absolute_time)
        size_field = state["size_field_name"]
        if size_field == "target_height_frac":
            height = max(1, round(state["size_value"] * canvas_height))
            width = max(1, round(native_width * height / native_height))
        else:
            width = max(1, round(state["size_value"] * canvas_width))
            height = max(1, round(native_height * width / native_width))
        if source_clip is not None:
            image = Image.fromarray(source_clip.get_frame(local_time)).convert("RGBA")
            image = image.resize((width, height), Image.Resampling.LANCZOS)
        else:
            image = source.resize((width, height), Image.Resampling.LANCZOS)
        rotation = float(element.get("rotation", 0.0))
        if rotation:
            image = image.rotate(rotation, expand=True, resample=Image.Resampling.BICUBIC)
        opacity = max(0.0, min(1.0, state["opacity"]))
        if opacity != 1.0:
            alpha = image.getchannel("A").point(lambda value: round(value * opacity))
            image.putalpha(alpha)
        x, y = state["pos"]
        cached_position = _anchor_position(element["anchor"], x, y, image.width, image.height)
        cached_time = local_time
        cached_frame = image
        return image

    def frame(local_time: float) -> np.ndarray:
        return np.asarray(render_element(local_time).convert("RGB"))

    def mask_frame(local_time: float) -> np.ndarray:
        return np.asarray(
            render_element(local_time).getchannel("A"), dtype=float
        ) / 255.0

    def position(local_time: float) -> tuple[int, int]:
        render_element(local_time)
        return cached_position

    clip = VideoClip(
        frame_function=frame,
        duration=duration,
        has_constant_size=False,
    )
    if source_clip is not None:
        clip._visual_source = source_clip
    mask = VideoClip(
        frame_function=mask_frame,
        is_mask=True,
        duration=duration,
        has_constant_size=False,
    )
    result = clip.with_mask(mask).with_position(position)
    if source_clip is not None:
        result._visual_source = source_clip
        original_close = result.close

        def close() -> None:
            original_close()
            source_clip.close()

        result.close = close
    return result


def build_static_scene_clip(
    script: dict[str, Any],
    scene: dict[str, Any],
    scene_manifest: dict[str, Any],
    assets_root: Path,
    manifest: dict[str, Any] | None = None,
    *,
    caption_start_offset_sec: float = 0.0,
    background_clip: VideoClip | None = None,
    background_key: str | None = None,
):
    """Build one full-resolution scene with animated element layers."""
    resolution = tuple(script["project"]["resolution"])
    duration = scene_duration_sec(scene, scene_manifest)
    registry = script["asset_registry"]
    background_path = _asset_path(
        registry,
        background_key if background_key is not None else scene["bg"],
        assets_root,
    )
    cache = AssetDimensionCache()
    layers = [
        background_clip
        if background_clip is not None
        else _cover_background(background_path, resolution, duration)
    ]
    if manifest is None:
        layers.extend(
            _element_clip(
                element, registry, assets_root, resolution, duration, cache
            )
            for element in sorted(
                scene.get("elements", []), key=lambda item: item.get("z_index", 0)
            )
        )
    else:
        layers.extend(
            _animated_element_clip(
                element,
                scene,
                scene_manifest,
                manifest,
                registry,
                assets_root,
                resolution,
                duration,
                cache,
            )
            for element in sorted(
                scene.get("elements", []), key=lambda item: item.get("z_index", 0)
            )
        )
    if manifest is None:
        caption = build_static_caption_clip(script, scene, resolution, duration)
    else:
        camera = _camera_value(scene, "camera")
        if _camera_value(camera, "moves", []):
            visual = CompositeVideoClip(layers, size=resolution).with_duration(duration)
            camera_manifest = dict(manifest)
            camera_manifest["_asset_registry"] = registry
            camera_manifest["_assets_root"] = assets_root
            visual = _camera_clip(
                visual, scene, scene_manifest, camera_manifest, resolution
            )
            layers = [visual]
        caption = build_animated_caption_clip(
            script,
            scene,
            scene_manifest,
            manifest,
            resolution,
            duration,
        )
    layers.append(caption.with_start(caption_start_offset_sec))
    return CompositeVideoClip(layers, size=resolution).with_duration(duration)


def caption_text_for_scene(scene: dict[str, Any]) -> str:
    """Return the narration text represented by a legacy or segmented scene."""
    narration_text = scene.get("narration_text")
    if isinstance(narration_text, str):
        return " ".join(spoken_words(narration_text))
    segments = scene.get("narration_segments")
    if not isinstance(segments, list):
        raise ValueError("Scene must define narration_text or narration_segments.")
    texts = [
        segment.get("text")
        if isinstance(segment, dict)
        else getattr(segment, "text", None)
        for segment in segments
    ]
    if len(texts) != len(segments):
        raise ValueError("Scene narration_segments must contain text values.")
    return " ".join(spoken_words(" ".join(texts)))


def _caption_font(style: dict[str, Any]) -> str | None:
    requested = style.get("font")
    if isinstance(requested, str) and Path(requested).is_file():
        return requested
    for candidate in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf",
    ):
        if Path(candidate).is_file():
            return candidate
    return None


def _wrap_caption(text: str, font_path: str | None, font_size: int, max_width: int) -> str:
    """Wrap caption words without splitting individual words."""
    font = ImageFont.truetype(font_path, font_size) if font_path else ImageFont.load_default(font_size)
    lines: list[str] = []
    line = ""
    for word in text.split():
        candidate = f"{line} {word}".strip()
        if line and font.getlength(candidate) > max_width:
            lines.append(line)
            line = word
        else:
            line = candidate
    if line:
        lines.append(line)
    return "\n".join(lines)


def resolve_caption_style(script: dict[str, Any], scene: dict[str, Any]) -> dict[str, Any]:
    """Merge a scene caption override over the project's caption defaults."""
    project_style = script.get("project", {}).get("caption_style") or {}
    scene_style = scene.get("caption_style") or {}
    return {**project_style, **scene_style}


def build_animated_caption_clip(
    script: dict[str, Any],
    scene: dict[str, Any],
    scene_manifest: dict[str, Any],
    manifest: dict[str, Any],
    resolution: tuple[int, int],
    duration: float,
) -> VideoClip:
    """Build a cached, word-highlighted caption layer for an aligned scene."""
    if isinstance(manifest.get("narration_segments"), list):
        return _build_segmented_caption_clip(
            script,
            scene,
            scene_manifest,
            manifest,
            resolution,
            duration,
        )
    style = resolve_caption_style(script, scene)
    chunks = wrap_caption_lines(
        caption_text_for_scene(scene),
        int(style.get("words_per_chunk", 3)),
        (
            int(style["max_chars_per_line"])
            if style.get("max_chars_per_line") is not None
            else None
        ),
        style=style,
        resolution=resolution,
    )
    timestamps = manifest.get("word_timestamps")
    if not isinstance(timestamps, list):
        raise ValueError("Manifest must contain word_timestamps for animated captions.")
    image_cache = CaptionImageCache(style, resolution)
    cached_time: float | None = None
    cached_rendered = None
    cached_active: tuple[int, int] | None = None

    def resolve_frame(local_time: float):
        nonlocal cached_time, cached_rendered, cached_active
        if cached_time == local_time:
            return cached_rendered, cached_active
        absolute_time = float(scene_manifest["start_time_sec"]) + local_time
        active = resolve_active_caption(
            scene,
            absolute_time,
            chunks,
            timestamps,
            word_offset=int(scene_manifest["word_offset"]),
        )
        rendered = None if active is None else image_cache.get(chunks[active[0]], active[1])
        cached_time = local_time
        cached_active = active
        cached_rendered = rendered
        return rendered, active

    def frame(local_time: float) -> np.ndarray:
        rendered, _ = resolve_frame(float(local_time))
        if rendered is None:
            return np.zeros((1, 1, 3), dtype=np.uint8)
        return np.asarray(rendered.image.convert("RGB"))

    def mask_frame(local_time: float) -> np.ndarray:
        rendered, _ = resolve_frame(float(local_time))
        if rendered is None:
            return np.zeros((1, 1), dtype=float)
        return (
            np.asarray(rendered.image.getchannel("A"), dtype=float) / 255.0
        )

    def position(local_time: float) -> tuple[int, int]:
        rendered, _ = resolve_frame(float(local_time))
        if rendered is None:
            return 0, 0
        return rendered.position

    clip = VideoClip(
        frame_function=frame,
        duration=duration,
        has_constant_size=False,
    )
    mask = VideoClip(
        frame_function=mask_frame,
        is_mask=True,
        duration=duration,
        has_constant_size=False,
    )
    clip = clip.with_mask(mask).with_position(position)
    clip.caption_image_cache = image_cache
    return clip


def _build_segmented_caption_clip(
    script: dict[str, Any],
    scene: dict[str, Any],
    scene_manifest: dict[str, Any],
    manifest: dict[str, Any],
    resolution: tuple[int, int],
    duration: float,
) -> VideoClip:
    style = resolve_caption_style(script, scene)
    all_timestamps = manifest.get("word_timestamps")
    if not isinstance(all_timestamps, list):
        raise ValueError("Manifest must contain word_timestamps for segmented captions.")
    voice_order: list[str] = []
    for timestamp in all_timestamps:
        voice_id = timestamp.get("voice_id")
        if isinstance(voice_id, str) and voice_id not in voice_order:
            voice_order.append(voice_id)
    scene_id = scene.get("id")
    segment_records = [
        record
        for record in manifest["narration_segments"]
        if isinstance(record, dict) and record.get("scene_id") == scene_id
    ]
    record_order = {
        str(record["id"]): index for index, record in enumerate(segment_records)
    }
    track_data: list[dict[str, Any]] = []
    scene_timestamps = [
        timestamp
        for timestamp in all_timestamps
        if isinstance(timestamp, dict) and timestamp.get("scene_id") == scene_id
    ]
    for voice_id in voice_order:
        timestamps = [
            timestamp
            for timestamp in scene_timestamps
            if timestamp.get("voice_id") == voice_id
        ]
        if not timestamps:
            continue
        track_style = {
            **style,
            "highlight_color": highlight_color_for_voice(
                style, voice_id, voice_order
            ),
        }
        chunks = wrap_caption_lines(
            " ".join(str(timestamp["word"]) for timestamp in timestamps),
            int(track_style.get("words_per_chunk", 3)),
            (
                int(track_style["max_chars_per_line"])
                if track_style.get("max_chars_per_line") is not None
                else None
            ),
            style=track_style,
            resolution=resolution,
        )
        track_data.append(
            {
                "voice_id": voice_id,
                "timestamps": timestamps,
                "chunks": chunks,
                "cache": CaptionImageCache(track_style, resolution),
            }
        )

    def segment_times(record: dict[str, Any]) -> tuple[float, float]:
        start = record.get("start_sec", record.get("start_time_sec"))
        end = record.get("end_sec", record.get("end_time_sec"))
        if not isinstance(start, (int, float)) or not isinstance(end, (int, float)):
            raise ValueError("Manifest narration segments must contain start and end times.")
        return float(start), float(end)

    def visibility_end(record: dict[str, Any]) -> float:
        start, end = segment_times(record)
        overlaps = any(
            start < other_end
            and other_start < end
            and record.get("voice_id") != other.get("voice_id")
            for other in segment_records
            if other.get("id") != record.get("id")
            for other_start, other_end in [segment_times(other)]
        )
        return end + 0.5 if overlaps else end

    def active_voice_records(absolute_time: float) -> dict[str, dict[str, Any]]:
        by_voice: dict[str, dict[str, Any]] = {}
        for record in segment_records:
            start, _end = segment_times(record)
            if start <= absolute_time < visibility_end(record):
                voice_id = str(record["voice_id"])
                previous = by_voice.get(voice_id)
                if previous is None or (
                    segment_times(previous)[0],
                    record_order.get(str(previous["id"]), -1),
                ) < (
                    start,
                    record_order.get(str(record["id"]), -1),
                ):
                    by_voice[voice_id] = record
        return by_voice

    cached_time: float | None = None
    cached_rendered: RenderedCaption | None = None

    def resolve_frame(local_time: float) -> RenderedCaption | None:
        nonlocal cached_time, cached_rendered
        if cached_time == local_time:
            return cached_rendered
        absolute_time = float(scene_manifest["start_time_sec"]) + local_time
        visible_records = active_voice_records(absolute_time)
        ordered_tracks = sorted(
            (
                (record, track)
                for track in track_data
                if (record := visible_records.get(track["voice_id"])) is not None
            ),
            key=lambda item: (
                segment_times(item[0])[0],
                record_order.get(str(item[0]["id"]), -1),
            ),
            reverse=True,
        )
        rendered_tracks: list[RenderedCaption] = []
        for record, track in ordered_tracks:
            active = resolve_active_caption_track(
                absolute_time,
                track["chunks"],
                track["timestamps"],
            )
            if active is not None:
                rendered_tracks.append(
                    track["cache"].get(track["chunks"][active[0]], active[1])
                )
        if not rendered_tracks:
            cached_time = local_time
            cached_rendered = None
            return None
        gap = max(4, int(style.get("font_size", 48) * 0.12))
        width = max(rendered.image.width for rendered in rendered_tracks)
        height = sum(rendered.image.height for rendered in rendered_tracks)
        height += gap * (len(rendered_tracks) - 1)
        image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        y = 0
        for rendered in rendered_tracks:
            x = (width - rendered.image.width) // 2
            image.alpha_composite(rendered.image, (x, y))
            y += rendered.image.height + gap
        result = type(rendered_tracks[0])(
            image=image,
            position=caption_position(image.size, resolution, style),
        )
        cached_time = local_time
        cached_rendered = result
        return result

    def frame(local_time: float) -> np.ndarray:
        rendered = resolve_frame(float(local_time))
        if rendered is None:
            return np.zeros((1, 1, 3), dtype=np.uint8)
        return np.asarray(rendered.image.convert("RGB"))

    def mask_frame(local_time: float) -> np.ndarray:
        rendered = resolve_frame(float(local_time))
        if rendered is None:
            return np.zeros((1, 1), dtype=float)
        return np.asarray(rendered.image.getchannel("A"), dtype=float) / 255.0

    def position(local_time: float) -> tuple[int, int]:
        rendered = resolve_frame(float(local_time))
        return (0, 0) if rendered is None else rendered.position

    clip = VideoClip(
        frame_function=frame,
        duration=duration,
        has_constant_size=False,
    )
    mask = VideoClip(
        frame_function=mask_frame,
        is_mask=True,
        duration=duration,
        has_constant_size=False,
    )
    return clip.with_mask(mask).with_position(position)


def build_static_caption_clip(
    script: dict[str, Any],
    scene: dict[str, Any],
    resolution: tuple[int, int],
    duration: float,
) -> TextClip:
    """Build a bottom-centered, static caption from the scene narration."""
    style = resolve_caption_style(script, scene)
    width, height = resolution
    font_size = int(style.get("font_size", max(24, round(height * 0.035))))
    horizontal_margin = max(24, round(width * 0.06))
    font_path = _caption_font(style)
    wrapped_text = _wrap_caption(
        caption_text_for_scene(scene),
        font_path,
        font_size,
        width - 2 * horizontal_margin,
    )
    text_clip = TextClip(
        font=font_path,
        text=wrapped_text,
        font_size=font_size,
        method="label",
        color=style.get("color", "#FFFFFF"),
        stroke_color=style.get("stroke_color", "#000000"),
        stroke_width=int(style.get("stroke_width", 0)),
        text_align="center",
        horizontal_align="center",
        vertical_align="center",
        margin=(horizontal_margin // 2, max(12, font_size // 4)),
        duration=duration,
    )
    caption_y = caption_position(
        (text_clip.w, text_clip.h),
        resolution,
        style,
    )[1]
    return text_clip.with_position(("center", caption_y))


def attach_scene_narration(
    scene_clip,
    scene_manifest: dict[str, Any],
    manifest: dict[str, Any],
    project_dir: Path,
):
    """Attach either legacy global audio or sequential segment audio."""
    segment_records = manifest.get("narration_segments")
    if isinstance(segment_records, list):
        scene_id = scene_manifest.get("id")
        scene_start = float(scene_manifest["start_time_sec"])
        scene_end = float(scene_manifest["end_time_sec"])
        scene_segments = [
            record
            for record in segment_records
            if isinstance(record, dict) and record.get("scene_id") == scene_id
        ]
        if not scene_segments:
            raise ValueError(f"No narration segments found for scene {scene_id!r}.")
        audio_layers = []
        for record in scene_segments:
            audio_value = record.get("audio_path")
            if not isinstance(audio_value, str) or not audio_value:
                raise ValueError(f"Segment {record.get('id', '<unnamed>')!r} has no audio path.")
            audio_path = Path(audio_value)
            if not audio_path.is_absolute():
                audio_path = project_dir / audio_path
            if not audio_path.is_file():
                raise FileNotFoundError(f"Narration audio file does not exist: {audio_path}")
            source_audio = AudioFileClip(str(audio_path))
            segment_start = float(record.get("start_sec", record["start_time_sec"]))
            audio_layers.append(source_audio.with_start(segment_start - scene_start))
        audio = CompositeAudioClip(audio_layers).with_duration(scene_end - scene_start)
        return scene_clip.with_audio(audio)

    audio_path = Path(manifest["narration_audio_path"])
    if not audio_path.is_absolute():
        audio_path = project_dir / audio_path
    if not audio_path.is_file():
        raise FileNotFoundError(f"Narration audio file does not exist: {audio_path}")
    start = float(scene_manifest["start_time_sec"])
    end = float(scene_manifest["end_time_sec"])
    if end <= start:
        raise ValueError("Scene narration end time must be greater than its start time.")
    source_audio = AudioFileClip(str(audio_path))
    try:
        validate_audio_timing(float(source_audio.duration), end)
    except ValueError as exc:
        duration = source_audio.duration
        source_audio.close()
        raise ValueError(
            f"Scene narration ends at {end:.3f}s, but the active audio ends at "
            f"{duration:.3f}s. {exc}"
        ) from exc
    normalized_end = min(end, float(source_audio.duration))
    if normalized_end <= start:
        source_audio.close()
        raise ValueError(
            f"Scene narration range is invalid after audio-duration normalization: "
            f"start={start:.6f}s, end={normalized_end:.6f}s."
        )
    audio = source_audio.subclipped(start, normalized_end)
    return scene_clip.with_audio(audio)


def build_full_video_clip(
    script: dict[str, Any],
    manifest: dict[str, Any],
    assets_root: Path,
    project_dir: Path,
    *,
    show_scene_numbers: bool = False,
):
    """Build scenes on one timeline, overlapping real scene transitions."""
    scenes = script.get("scenes", [])
    scene_manifests = manifest.get("scenes", [])
    if len(scene_manifests) != len(scenes):
        raise ValueError(
            "The build manifest scene count does not match the script scene count."
        )
    if not scenes:
        raise ValueError("Cannot build a video without scenes.")

    scene_offsets = build_scene_final_offsets(script, manifest)
    backgrounds = effective_backgrounds(script)
    timelines: dict[int, BackgroundTimeline] = {}
    run_for_scene: dict[int, tuple[int, float, float]] = {}
    for run_start, run_end, background_key, origin, end in _background_runs(
        script,
        backgrounds,
        scene_offsets,
    ):
        run_has_inheritance = any(
            (
                scene.get("bg") is None
                if hasattr(scene, "get")
                else getattr(scene, "bg", None) is None
            )
            for scene in scenes[run_start:run_end]
        )
        if run_has_inheritance:
            path = _asset_path(script["asset_registry"], background_key, assets_root)
            timelines[run_start] = BackgroundTimeline(
                path,
                tuple(script["project"]["resolution"]),
                max(0.001, end - origin),
            )
        for scene_index in range(run_start, run_end):
            run_for_scene[scene_index] = (run_start, origin, end)

    scene_units = []
    for index, (scene, scene_manifest) in enumerate(zip(scenes, scene_manifests)):
        timeline_info = run_for_scene[index]
        run_start, run_origin, _run_end = timeline_info
        timeline = timelines.get(run_start)
        pause = scene_offsets[index].pause_before_sec
        background_key = backgrounds[index]
        background_clip = None
        pause_background_clip = None
        if timeline is not None:
            background_clip = timeline.clip(
                scene_offsets[index].visual_start_sec + pause - run_origin,
                float(scene_offsets[index].unit_duration_sec - pause),
            )
            if pause:
                pause_background_clip = timeline.clip(
                    scene_offsets[index].visual_start_sec - run_origin,
                    pause,
                )
        scene_clip = build_static_scene_clip(
            script,
            scene,
            scene_manifest,
            assets_root,
            manifest,
            caption_start_offset_sec=scene_offsets[index].transition_duration_sec,
            background_clip=background_clip,
            background_key=background_key,
        )
        narrated_clip = attach_scene_narration(
            scene_clip,
            scene_manifest,
            manifest,
            project_dir,
        )
        if pause:
            if pause_background_clip is None:
                background_path = _asset_path(
                    script["asset_registry"], background_key, assets_root
                )
                pause_background_clip = _cover_background(
                    background_path,
                    tuple(script["project"]["resolution"]),
                    pause,
                )
            silent_audio = AudioClip(
                frame_function=lambda t: [0.0, 0.0],
                duration=pause,
                fps=44100,
            )
            unit_parts = [pause_background_clip.with_audio(silent_audio)]
        else:
            unit_parts = []
        unit_parts.append(narrated_clip)
        unit = concatenate_videoclips(unit_parts, method="chain")
        scene_units.append(unit)

    positioned = []
    audio_layers = []
    layer_indices = list(range(len(scene_units)))
    for index in range(len(scene_units) - 2, -1, -1):
        next_transition = script["scenes"][index + 1].get("transition_in")
        if (
            next_transition is not None
            and next_transition.get("type") == "push"
            and next_transition.get("style") == "soft"
        ):
            layer_indices[index] = max(
                layer_indices[index],
                layer_indices[index + 1] + 1,
            )
    for index, (unit, offset) in enumerate(zip(scene_units, scene_offsets)):
        transition = script["scenes"][index].get("transition_in")
        outgoing = script["scenes"][index + 1].get("transition_in") if index + 1 < len(scene_units) else None
        outgoing_start = (
            scene_offsets[index + 1].final_start_sec
            if outgoing is not None
            else None
        )
        unit = _apply_scene_transition_effects(
            unit,
            transition,
            outgoing,
            tuple(script["project"]["resolution"]),
            scene_start_sec=offset.visual_start_sec,
            outgoing_transition_start_sec=outgoing_start,
        )
        positioned.append(
            unit.with_start(offset.visual_start_sec).with_layer_index(layer_indices[index])
        )
        if unit.audio is not None:
            audio_layers.append(unit.audio.with_start(offset.final_start_sec))

    final_duration = max(
        offset.final_start_sec + offset.unit_duration_sec
        for offset in scene_offsets
    )
    final_clip = CompositeVideoClip(
        positioned,
        size=tuple(script["project"]["resolution"]),
    ).with_duration(final_duration)
    if show_scene_numbers:
        width, height = tuple(script["project"]["resolution"])
        overlays = []
        margin = max(12, round(min(width, height) * 0.035))
        font_size = max(18, round(height * 0.04))
        stroke_width = max(2, round(font_size * 0.12))
        for index, offset in enumerate(scene_offsets, start=1):
            number = TextClip(
                font=_caption_font({}),
                text=str(index),
                font_size=font_size,
                color="white",
                stroke_color="black",
                stroke_width=stroke_width,
                method="label",
            ).with_duration(offset.unit_duration_sec).with_start(
                offset.final_start_sec
            )
            number = number.with_position(
                (width - number.w - margin, margin)
            )
            overlays.append(number)
        final_clip = CompositeVideoClip(
            [final_clip, *overlays],
            size=(width, height),
        ).with_duration(final_duration).with_audio(final_clip.audio)
    if not audio_layers:
        raise RuntimeError("Final assembled video has no narration audio to mix.")
    narration_timeline = CompositeAudioClip(audio_layers).with_duration(final_duration)
    final_clip = final_clip.with_audio(
        build_final_audio_mix(
            narration_timeline,
            script,
            manifest,
            assets_root,
            project_dir,
        )
    )
    return final_clip


def _apply_scene_transition_effects(
    clip: VideoClip,
    incoming: dict[str, Any] | None,
    outgoing: dict[str, Any] | None,
    resolution: tuple[int, int],
    *,
    scene_start_sec: float = 0.0,
    outgoing_transition_start_sec: float | None = None,
) -> VideoClip:
    """Apply entrance and exit transitions without overwriting clip attributes."""
    width, height = resolution
    incoming_duration = (
        float(incoming["duration_sec"]) if incoming is not None else 0.0
    )
    outgoing_duration = (
        float(outgoing["duration_sec"]) if outgoing is not None else 0.0
    )
    incoming_type = incoming["type"] if incoming is not None else None
    outgoing_type = outgoing["type"] if outgoing is not None else None
    outgoing_feather = (
        max(1, round(SOFT_PUSH_FEATHER_FRAC * width))
        if outgoing_type == "push" and outgoing.get("style") == "soft"
        else 0
    )

    if incoming_type == "zoom_out":
        zoom_scale = float(incoming.get("zoom_scale", 1.3))

        def scale_at_time(t: float) -> float:
            progress = min(1.0, max(0.0, float(t) / incoming_duration))
            return zoom_scale - (zoom_scale - 1.0) * progress

        clip = clip.with_effects([vfx.Resize(scale_at_time)])

    def position(t: float) -> tuple[float, float]:
        local_time = float(t)
        if incoming_type == "zoom_out" and local_time < incoming_duration:
            scale = (
                float(incoming.get("zoom_scale", 1.3))
                - (float(incoming.get("zoom_scale", 1.3)) - 1.0)
                * min(1.0, max(0.0, local_time / incoming_duration))
            )
            return (width * (1.0 - scale) / 2.0, height * (1.0 - scale) / 2.0)
        if incoming_type == "push" and local_time < incoming_duration:
            if incoming.get("style") == "soft":
                return 0.0, 0.0
            progress = min(1.0, max(0.0, local_time / incoming_duration))
            start_x = width if incoming["direction"] == "left" else -width
            return start_x * (1.0 - progress), 0.0
        if (
            outgoing_type == "push"
            and outgoing.get("style") != "soft"
            and local_time >= clip.duration - outgoing_duration
        ):
            progress = min(
                1.0,
                max(
                    0.0,
                    (local_time - (clip.duration - outgoing_duration))
                    / outgoing_duration,
                ),
            )
            destination = -width if outgoing["direction"] == "left" else width
            return destination * progress, 0.0
        return 0.0, 0.0

    clip = clip.with_position(position)

    if (
        incoming_type in {"crossfade", "zoom_out"}
        or outgoing_type in {"crossfade", "zoom_out"}
        or outgoing_feather
    ):
        if clip.mask is None:
            clip = clip.with_mask()
        base_mask = clip.mask

        def mask_frame(t):
            local_time = float(t)
            # Soft pushes are full-canvas scene wipes. Only the outgoing
            # scene is masked; the incoming scene remains fully opaque below.
            if outgoing_feather:
                mask = np.ones((height, width), dtype=float)
            else:
                mask = np.asarray(base_mask.get_frame(t), dtype=float)
                if mask.ndim != 2:
                    mask = np.ones((height, width), dtype=float)
            if incoming_type in {"crossfade", "zoom_out"} and local_time < incoming_duration:
                mask *= min(1.0, max(0.0, local_time / incoming_duration))
            if outgoing_type in {"crossfade", "zoom_out"}:
                exit_start = float(clip.duration) - outgoing_duration
                if local_time >= exit_start:
                    mask *= min(
                        1.0,
                        max(0.0, (float(clip.duration) - local_time) / outgoing_duration),
                    )
            if outgoing_feather and outgoing_type == "push":
                transition_start = (
                    outgoing_transition_start_sec
                    if outgoing_transition_start_sec is not None
                    else scene_start_sec + clip.duration - outgoing_duration
                )
                absolute_time = scene_start_sec + local_time
                progress = min(
                    1.0,
                    max(
                        0.0,
                        (absolute_time - transition_start) / outgoing_duration,
                    ),
                )
                positions = np.arange(width, dtype=float)
                if outgoing["direction"] == "left":
                    boundary = (
                        width
                        + outgoing_feather / 2.0
                        - (width + outgoing_feather) * progress
                    )
                    ramp = np.clip(
                        (boundary - positions + outgoing_feather / 2.0)
                        / outgoing_feather,
                        0.0,
                        1.0,
                    )
                else:
                    boundary = (
                        -outgoing_feather / 2.0
                        + (width + outgoing_feather) * progress
                    )
                    ramp = np.clip(
                        (positions - boundary + outgoing_feather / 2.0)
                        / outgoing_feather,
                        0.0,
                        1.0,
                    )
                mask *= ramp[np.newaxis, :]
            return mask

        clip.mask = VideoClip(
            frame_function=mask_frame,
            is_mask=True,
            duration=clip.duration,
            has_constant_size=True,
        )
    return clip
