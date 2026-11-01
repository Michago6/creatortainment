"""Shared loading and duration normalization for visual assets."""

from __future__ import annotations

from bisect import bisect_right
import json
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


def _vfr_frame_timestamps(path: Path) -> list[float] | None:
    """Return decoded frame PTS values when the decoded cadence is irregular."""
    ffprobe = shutil.which("ffprobe")
    if ffprobe is None:
        return None
    frames = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_frames",
            "-show_entries",
            "frame=best_effort_timestamp_time",
            "-of",
            "json",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    timestamps = [
        float(frame["best_effort_timestamp_time"])
        for frame in json.loads(frames.stdout).get("frames", [])
        if frame.get("best_effort_timestamp_time") is not None
    ]
    if len(timestamps) < 3:
        return None
    intervals = np.diff(timestamps)
    median_interval = float(np.median(intervals))
    tolerance = max(1e-4, median_interval * 1e-3)
    return timestamps if float(np.max(intervals) - np.min(intervals)) > tolerance else None


def _make_source_times_safe(clip: VideoFileClip, path: Path) -> VideoFileClip:
    """Map decoder requests to available source frames without overruns."""
    reader = clip.reader
    timestamps = _vfr_frame_timestamps(path)
    source_frame_count = (
        len(timestamps)
        if timestamps is not None
        else _decoded_frame_count(path, int(reader.n_frames))
    )
    if timestamps is None:
        original_frame_function = clip.frame_function

        def safe_frame_function(time: float) -> np.ndarray:
            frame_number = reader.get_frame_number(max(0.0, float(time)))
            frame_number = min(max(frame_number, 0), source_frame_count - 1)
            return original_frame_function(frame_number / float(clip.fps))

    else:
        # MoviePy's raw reader may resample irregular streams to its nominal
        # FPS. Decode VFR frames ourselves with vsync disabled, then address
        # that ordered decoded stream by the PTS-selected frame index.
        ffmpeg = shutil.which("ffmpeg")
        if ffmpeg is None:
            raise RuntimeError("FFmpeg is required to decode VFR video assets.")
        frame_bytes = reader.depth * reader.size[0] * reader.size[1]
        reader.close()
        decoder: subprocess.Popen[bytes] | None = None
        decoded_index = -1
        decoded_frame: np.ndarray | None = None

        def open_decoder() -> None:
            nonlocal decoder, decoded_index, decoded_frame
            if decoder is not None:
                decoder.kill()
                decoder.wait()
            decoder = subprocess.Popen(
                [
                    ffmpeg,
                    "-v",
                    "error",
                    "-i",
                    str(path),
                    "-vsync",
                    "0",
                    "-f",
                    "image2pipe",
                    "-vf",
                    f"scale={reader.size[0]}:{reader.size[1]}",
                    "-pix_fmt",
                    reader.pixel_format,
                    "-vcodec",
                    "rawvideo",
                    "-",
                ],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )
            decoded_index = -1
            decoded_frame = None

        def read_decoded_frame() -> np.ndarray:
            assert decoder is not None and decoder.stdout is not None
            data = decoder.stdout.read(frame_bytes)
            if len(data) != frame_bytes:
                raise IOError(f"Unable to decode VFR frame from {path}.")
            frame = np.frombuffer(data, dtype=np.uint8)
            frame.shape = (reader.size[1], reader.size[0], reader.depth)
            return frame

        open_decoder()

        def safe_frame_function(time: float) -> np.ndarray:
            nonlocal decoded_index, decoded_frame
            requested_time = max(0.0, float(time))
            frame_number = bisect_right(timestamps, requested_time) - 1
            frame_number = min(max(frame_number, 0), source_frame_count - 1)
            if frame_number < decoded_index:
                open_decoder()
            if frame_number > decoded_index:
                while decoded_index < frame_number:
                    decoded_frame = read_decoded_frame()
                    decoded_index += 1
            assert decoded_frame is not None
            return decoded_frame

        original_close = clip.close

        def close() -> None:
            if decoder is not None:
                decoder.kill()
                decoder.wait()
            original_close()

        clip.close = close

    clip.frame_function = safe_frame_function
    return clip


def _load_gif_clip(path: Path) -> VideoClip:
    """Decode GIF frames and timing with Pillow instead of MoviePy metadata."""
    frames: list[np.ndarray] = []
    durations: list[float] = []
    with Image.open(path) as image:
        frame_count = int(getattr(image, "n_frames", 1))
        for frame_index in range(frame_count):
            image.seek(frame_index)
            frames.append(np.asarray(image.convert("RGB")).copy())
            duration_ms = image.info.get("duration")
            duration_sec = (
                float(duration_ms) / 1000.0
                if isinstance(duration_ms, (int, float)) and duration_ms > 0
                else 0.0
            )
            durations.append(duration_sec)

    if not frames:
        raise ValueError(f"Animated visual asset has no usable frames: {path}")
    if len(frames) == 1:
        return VideoClip(
            frame_function=lambda _time: frames[0],
            duration=1.0,
            has_constant_size=True,
        ).with_fps(1.0)

    fallback_duration = 0.1
    durations = [
        duration if duration > 0.0 else fallback_duration
        for duration in durations
    ]
    cumulative = np.cumsum(durations).tolist()
    source_duration = cumulative[-1]
    source_fps = 1.0 / min(durations)

    def frame(time: float) -> np.ndarray:
        local_time = float(time) % source_duration
        frame_index = min(
            bisect_right(cumulative, local_time + 1e-10),
            len(frames) - 1,
        )
        return frames[frame_index]

    return VideoClip(
        frame_function=frame,
        duration=source_duration,
        has_constant_size=True,
    ).with_fps(source_fps)


def load_visual_clip(path: Path, duration: float) -> VideoClip:
    """Load a visual asset with no audio and normalize it to ``duration``."""
    if path.suffix.lower() == ".gif":
        clip = _load_gif_clip(path)
        return clip.with_duration(duration)
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
