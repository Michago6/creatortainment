"""Shared loading and duration normalization for visual assets."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from moviepy import ImageClip, VideoFileClip, VideoClip, vfx
from PIL import Image

ANIMATED_SUFFIXES = {".gif", ".mp4"}


def is_animated_visual(path: Path) -> bool:
    return path.suffix.lower() in ANIMATED_SUFFIXES


def load_visual_clip(path: Path, duration: float) -> VideoClip:
    """Load a visual asset with no audio and normalize it to ``duration``."""
    if is_animated_visual(path):
        clip: VideoClip = VideoFileClip(str(path), audio=False)
        if clip.duration is None or clip.duration <= 0:
            clip.close()
            raise ValueError(f"Animated visual asset has no usable duration: {path}")
        if clip.duration < duration:
            clip = clip.with_effects([vfx.Loop(duration=duration)])
        elif clip.duration > duration:
            clip = clip.subclipped(0, duration)
        return clip.with_duration(duration)
    return ImageClip(str(path)).with_duration(duration)


def visual_dimensions(path: Path) -> tuple[int, int]:
    """Return visual dimensions without assuming the asset is a PIL image."""
    if is_animated_visual(path):
        clip = VideoFileClip(str(path), audio=False)
        try:
            return int(clip.w), int(clip.h)
        finally:
            clip.close()
    with Image.open(path) as image:
        return image.size


def first_frame_image(path: Path) -> Image.Image:
    """Load a visual asset's first frame for static storyboard rendering."""
    if is_animated_visual(path):
        clip = VideoFileClip(str(path), audio=False)
        try:
            return Image.fromarray(np.asarray(clip.get_frame(0)).copy()).convert("RGBA")
        finally:
            clip.close()
    with Image.open(path) as image:
        return image.convert("RGBA")
