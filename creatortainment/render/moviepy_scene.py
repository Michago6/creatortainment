"""MoviePy 2.x static scene composition for the first video checkpoint."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
from moviepy import (
    AudioFileClip,
    AudioClip,
    CompositeVideoClip,
    ImageClip,
    TextClip,
    VideoClip,
    concatenate_videoclips,
)
from PIL import Image, ImageFont

from .mock import AssetDimensionCache, _asset_path
from .keyframes import resolve_element_state
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
    """Create a full-canvas dynamic clip driven by resolved element states."""
    path = _asset_path(registry, element["asset"], assets_root)
    source = Image.open(path).convert("RGBA")
    timed = timed_element(element, scene, scene_manifest, manifest)
    canvas_width, canvas_height = resolution
    native_width, native_height = dimension_cache.dimensions(path)
    cached_time: float | None = None
    cached_frame: Image.Image | None = None

    def render_rgba(local_time: float) -> Image.Image:
        nonlocal cached_time, cached_frame
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
        anchor = element["anchor"]
        if anchor == "top_left":
            left, top = round(x), round(y)
        elif anchor == "bottom_center":
            left, top = round(x - width / 2), round(y - height)
        else:
            left, top = round(x - width / 2), round(y - height / 2)
        canvas = Image.new("RGBA", (canvas_width, canvas_height))
        canvas.alpha_composite(image, (left, top))
        cached_time = local_time
        cached_frame = canvas
        return canvas

    def frame(local_time: float) -> np.ndarray:
        return np.asarray(render_rgba(local_time).convert("RGB"))

    def mask_frame(local_time: float) -> np.ndarray:
        return np.asarray(render_rgba(local_time).getchannel("A"), dtype=float) / 255.0

    clip = VideoClip(
        frame_function=frame,
        duration=duration,
        has_constant_size=True,
    )
    mask = VideoClip(
        frame_function=mask_frame,
        is_mask=True,
        duration=duration,
        has_constant_size=True,
    )
    return clip.with_mask(mask)


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
    layers.append(build_static_caption_clip(script, scene, resolution, duration))
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
    bottom_margin = max(24, round(height * 0.04))
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
    return text_clip.with_position(("center", height - text_clip.h - bottom_margin))


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
    """Build every scene in order and concatenate them with hard cuts."""
    scenes = script.get("scenes", [])
    scene_manifests = manifest.get("scenes", [])
    if len(scene_manifests) != len(scenes):
        raise ValueError(
            "The build manifest scene count does not match the script scene count."
        )
    if not scenes:
        raise ValueError("Cannot build a video without scenes.")

    scene_clips = []
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
        pause = float(scene.get("pause_before_sec", 0.0)) if index > 0 else 0.0
        if pause < 0:
            raise ValueError(f"Scene {scene.get('id', index)!r} has an invalid pause.")
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
            scene_clips.append(filler.with_audio(silent_audio))
        scene_clips.append(narrated_clip)
    return concatenate_videoclips(scene_clips, method="chain")
