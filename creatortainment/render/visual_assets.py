"""Shared loading and duration normalization for visual assets."""

from __future__ import annotations

from pathlib import Path
import shutil
import subprocess

import numpy as np
from moviepy import ImageClip, VideoFileClip, VideoClip, vfx
from PIL import Image

ANIMATED_SUFFIXES = {".gif", ".mp4"}


def is_animated_visual(path: Path) -> bool:
    return path.suffix.lower() in ANIMATED_SUFFIXES


def _decoded_frame_count(path: Path, fallback: int) -> int:
    """Return FFmpeg's actual decoded frame count when it is available."""
    ffprobe = shutil.which("ffprobe")
    if ffprobe is None:
        return fallback
    result = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-count_frames",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=nb_read_frames",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    count = int(result.stdout.strip())
    return count if count > 0 else fallback


def _make_source_times_safe(clip: VideoFileClip, path: Path) -> VideoFileClip:
    """Map decoder requests to an available source frame."""
    reader = clip.reader
    source_fps = float(clip.fps)
    source_frame_count = _decoded_frame_count(path, int(reader.n_frames))
    original_frame_function = clip.frame_function

    def safe_frame_function(time: float) -> np.ndarray:
        frame_number = reader.get_frame_number(max(0.0, float(time)))
        frame_number = min(max(frame_number, 0), source_frame_count - 1)
        return original_frame_function(frame_number / source_fps)

    clip.frame_function = safe_frame_function
    return clip


def load_visual_clip(path: Path, duration: float) -> VideoClip:
    """Load a visual asset with no audio and normalize it to ``duration``."""
    if is_animated_visual(path):
        clip = _make_source_times_safe(
            VideoFileClip(str(path), audio=False), path
        )
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
