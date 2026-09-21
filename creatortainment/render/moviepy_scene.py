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
    resolve_active_caption,
    wrap_caption_lines,
)
from ..audio.mixing import build_final_audio_mix
from .mock import AssetDimensionCache, _asset_path
from .keyframes import resolve_element_state
from .timeline import build_scene_final_offsets
from ..timeline import timed_element


def _cover_background(path: Path, resolution: tuple[int, int], duration: float) -> ImageClip:
    width, height = resolution
    clip = ImageClip(str(path))
    scale = max(width / clip.w, height / clip.h)
    resized = clip.resized(new_size=(round(clip.w * scale), round(clip.h * scale)))
    return resized.cropped(
        x_center=resized.w / 2,
        y_center=resized.h / 2,
        width=width,
        height=height,
    ).with_duration(duration)


def _element_clip(
    element: dict[str, Any],
    registry: dict[str, Any],
    assets_root: Path,
    resolution: tuple[int, int],
    duration: float,
    dimension_cache: AssetDimensionCache,
) -> ImageClip:
    path = _asset_path(registry, element["asset"], assets_root)
    image = ImageClip(str(path))
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
    path = _asset_path(registry, element["asset"], assets_root)
    source = Image.open(path).convert("RGBA")
    timed = timed_element(element, scene, scene_manifest, manifest)
    canvas_width, canvas_height = resolution
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
        image = source.resize((width, height), Image.Resampling.LANCZOS)
        opacity = max(0.0, min(1.0, state["opacity"]))
        if opacity != 1.0:
            alpha = image.getchannel("A").point(lambda value: round(value * opacity))
            image.putalpha(alpha)
        x, y = state["pos"]
        cached_position = _anchor_position(element["anchor"], x, y, width, height)
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
    mask = VideoClip(
        frame_function=mask_frame,
        is_mask=True,
        duration=duration,
        has_constant_size=False,
    )
    return clip.with_mask(mask).with_position(position)


def build_static_scene_clip(
    script: dict[str, Any],
    scene: dict[str, Any],
    scene_manifest: dict[str, Any],
    assets_root: Path,
    manifest: dict[str, Any] | None = None,
):
    """Build one full-resolution scene with animated element layers."""
    resolution = tuple(script["project"]["resolution"])
    duration = float(scene_manifest["duration_sec"])
    registry = script["asset_registry"]
    background_path = _asset_path(registry, scene["bg"], assets_root)
    cache = AssetDimensionCache()
    layers = [_cover_background(background_path, resolution, duration)]
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
        layers.append(build_static_caption_clip(script, scene, resolution, duration))
    else:
        layers.append(
            build_animated_caption_clip(
                script,
                scene,
                scene_manifest,
                manifest,
                resolution,
                duration,
            )
        )
    return CompositeVideoClip(layers, size=resolution).with_duration(duration)


def caption_text_for_scene(scene: dict[str, Any]) -> str:
    """Return the verbatim narration used for a scene's static caption."""
    return scene["narration_text"]


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
    style = resolve_caption_style(script, scene)
    chunks = wrap_caption_lines(
        caption_text_for_scene(scene),
        int(style.get("words_per_chunk", 3)),
        (
            int(style["max_chars_per_line"])
            if style.get("max_chars_per_line") is not None
            else None
        ),
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
        return np.ones((rendered.image.height, rendered.image.width), dtype=float)

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
        bg_color="#000000",
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
    """Attach the manifest's global narration slice to one scene clip."""
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
    if end > source_audio.duration + 0.001:
        duration = source_audio.duration
        source_audio.close()
        raise ValueError(
            f"Scene narration ends at {end:.3f}s, but the active audio ends at "
            f"{duration:.3f}s. Re-run align for this script to regenerate its manifest."
        )
    audio = source_audio.subclipped(start, end)
    return scene_clip.with_audio(audio)


def build_full_video_clip(
    script: dict[str, Any],
    manifest: dict[str, Any],
    assets_root: Path,
    project_dir: Path,
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

    scene_units = []
    scene_offsets = build_scene_final_offsets(script, manifest)
    for index, (scene, scene_manifest) in enumerate(zip(scenes, scene_manifests)):
        scene_clip = build_static_scene_clip(
            script,
            scene,
            scene_manifest,
            assets_root,
            manifest,
        )
        narrated_clip = attach_scene_narration(
            scene_clip,
            scene_manifest,
            manifest,
            project_dir,
        )
        pause = scene_offsets[index].pause_before_sec
        if pause:
            background_path = _asset_path(script["asset_registry"], scene["bg"], assets_root)
            filler = _cover_background(
                background_path,
                tuple(script["project"]["resolution"]),
                pause,
            )
            silent_audio = AudioClip(
                frame_function=lambda t: [0.0, 0.0],
                duration=pause,
                fps=44100,
            )
            unit_parts = [filler.with_audio(silent_audio)]
        else:
            unit_parts = []
        unit_parts.append(narrated_clip)
        unit = concatenate_videoclips(unit_parts, method="chain")
        scene_units.append(unit)

    positioned = []
    audio_layers = []
    for index, (unit, offset) in enumerate(zip(scene_units, scene_offsets)):
        transition = script["scenes"][index].get("transition_in")
        outgoing = script["scenes"][index + 1].get("transition_in") if index + 1 < len(scene_units) else None
        unit = _apply_scene_transition_effects(
            unit,
            transition,
            outgoing,
            tuple(script["project"]["resolution"]),
        )
        positioned.append(unit.with_start(offset.final_start_sec))
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
    incoming_feather = (
        max(1, round(float(incoming.get("feather_frac", 0.03)) * width))
        if incoming_type == "push" and incoming.get("style") == "soft"
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
            progress = min(1.0, max(0.0, local_time / incoming_duration))
            start_x = width if incoming["direction"] == "left" else -width
            overlap = incoming_feather * (1.0 - progress)
            overlap_sign = -1.0 if incoming["direction"] == "left" else 1.0
            return start_x * (1.0 - progress) + overlap_sign * overlap, 0.0
        if outgoing_type == "push" and local_time >= clip.duration - outgoing_duration:
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

    if incoming_type == "push" and incoming.get("style") == "soft":
        clip = _apply_soft_push_mask(
            clip,
            incoming,
            incoming_duration,
            width,
            height,
        )

    if incoming_type in {"crossfade", "zoom_out"} or outgoing_type in {
        "crossfade",
        "zoom_out",
    }:
        if clip.mask is None:
            clip = clip.with_mask()
        base_mask = clip.mask

        def opacity_at_time(t: float) -> float:
            local_time = float(t)
            if incoming_type in {"crossfade", "zoom_out"} and local_time < incoming_duration:
                return min(1.0, max(0.0, local_time / incoming_duration))
            if outgoing_type in {"crossfade", "zoom_out"}:
                exit_start = float(clip.duration) - outgoing_duration
                if local_time >= exit_start:
                    return min(
                        1.0,
                        max(0.0, (float(clip.duration) - local_time) / outgoing_duration),
                    )
            return 1.0

        clip.mask = base_mask.transform(
            lambda get_frame, t: get_frame(t) * opacity_at_time(t),
            keep_duration=True,
        )
    return clip


def _apply_soft_push_mask(
    clip: VideoClip,
    transition: dict[str, Any],
    duration: float,
    width: int,
    height: int,
) -> VideoClip:
    """Feather only the incoming push edge during its entrance window."""
    feather = max(1, round(float(transition.get("feather_frac", 0.03)) * width))
    if clip.mask is None:
        clip = clip.with_mask()
    base_mask = clip.mask
    direction = transition["direction"]

    def mask_frame(get_frame, t):
        current = np.asarray(get_frame(t), dtype=float)
        if float(t) >= duration:
            return current
        if direction == "left":
            ramp = np.clip(np.arange(width, dtype=float) / feather, 0.0, 1.0)
        else:
            ramp = np.clip(
                np.arange(width - 1, -1, -1, dtype=float) / feather,
                0.0,
                1.0,
            )
        return current * ramp[np.newaxis, :]

    clip.mask = base_mask.transform(mask_frame, keep_duration=True)
    return clip


def _apply_push_transition(
    clip: VideoClip,
    transition: dict[str, Any],
    duration: float,
    resolution: tuple[int, int],
) -> VideoClip:
    """Slide a scene into place, optionally feathering its leading edge."""
    width, height = resolution
    direction = transition["direction"]
    incoming_from = width if direction == "left" else -width

    def position(t: float) -> tuple[float, float]:
        progress = min(1.0, max(0.0, float(t) / duration))
        x = incoming_from * (1.0 - progress)
        return x, 0

    result = clip.with_position(position)
    if transition.get("style") != "soft":
        return result

    feather = max(1, round(float(transition.get("feather_frac", 0.03)) * width))
    base_mask = result.mask

    def mask_frame(t: float) -> np.ndarray:
        mask = np.ones((height, width), dtype=float)
        if direction == "left":
            ramp = np.clip(np.arange(width, dtype=float) / feather, 0.0, 1.0)
        else:
            ramp = np.clip(
                (np.arange(width, 0, -1, dtype=float)) / feather,
                0.0,
                1.0,
            )
        mask *= ramp[np.newaxis, :]
        if base_mask is not None:
            existing = np.asarray(base_mask.get_frame(t), dtype=float)
            if existing.shape == mask.shape:
                mask *= existing
        return mask

    return result.with_mask(
        VideoClip(
            frame_function=mask_frame,
            is_mask=True,
            duration=clip.duration,
            has_constant_size=True,
        )
    )


def _apply_push_outgoing(
    clip: VideoClip,
    transition: dict[str, Any],
    duration: float,
    resolution: tuple[int, int],
) -> VideoClip:
    """Slide the outgoing scene off the edge during its final transition."""
    width, _ = resolution
    direction = transition["direction"]
    destination = -width if direction == "left" else width
    start_time = float(clip.duration) - duration

    def position(t: float) -> tuple[float, float]:
        progress = min(
            1.0,
            max(0.0, (float(t) - start_time) / duration),
        )
        return destination * progress, 0

    return clip.with_position(position)
