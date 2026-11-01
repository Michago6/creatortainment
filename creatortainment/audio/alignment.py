"""Slice global narration alignment data into scene ranges."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
import subprocess
from typing import Any, Iterable

import numpy as np

from .tokenize import spoken_words


BOUNDARY_FRAME_SEC = 0.005
BOUNDARY_MIN_QUIET_SEC = 0.015
BOUNDARY_SEARCH_AFTER_NEXT_START_SEC = 0.18
BOUNDARY_QUIET_RMS = 0.006
BOUNDARY_QUIET_HIGH_FREQ_RMS = 0.0025
AUDIO_BOUNDARY_ALGORITHM_VERSION = 1


class AudioDecodeError(ValueError):
    """Narration audio could not be decoded for optional boundary analysis."""


@dataclass(frozen=True)
class SceneAlignment:
    id: str
    word_offset: int
    word_count: int
    start_time_sec: float
    end_time_sec: float
    duration_sec: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def align_scenes(
    scenes: Iterable[dict[str, Any]],
    word_timestamps: list[dict[str, Any]],
    *,
    pause_default_sec: float = 0.3,
    narration_duration_sec: float | None = None,
    audio_path: Path | None = None,
) -> list[SceneAlignment]:
    scene_list = list(scenes)
    scene_ranges: list[tuple[dict[str, Any], int, list[dict[str, Any]]]] = []
    global_offset = 0
    for scene_number, scene in enumerate(scene_list):
        words = spoken_words(scene["narration_text"])
        word_count = len(words)
        end_offset = global_offset + word_count
        if end_offset > len(word_timestamps):
            raise ValueError(
                f"Alignment has {len(word_timestamps)} words but scene "
                f"{scene.get('id', scene_number)!r} requires index {end_offset - 1}."
            )
        if word_count == 0:
            raise ValueError(f"Scene {scene.get('id', scene_number)!r} has no narration words.")
        scene_timestamps = word_timestamps[global_offset:end_offset]
        scene_ranges.append((scene, global_offset, scene_timestamps))
        global_offset = end_offset
    if global_offset != len(word_timestamps):
        raise ValueError(
            f"Alignment contains {len(word_timestamps) - global_offset} unused word timestamps."
        )

    starts = [float(scene_timestamps[0]["start"]) for _, _, scene_timestamps in scene_ranges]
    ends: list[float] = []
    for index, (_scene, _word_offset, scene_timestamps) in enumerate(scene_ranges):
        final_word_end = float(scene_timestamps[-1]["end"])
        if index + 1 < len(scene_ranges):
            next_start = float(scene_ranges[index + 1][2][0]["start"])
            if next_start < final_word_end:
                raise ValueError(
                    f"Alignment overlaps scenes {scene.get('id', index)!r} and "
                    f"{scene_ranges[index + 1][0].get('id', index + 1)!r}: "
                    f"next scene starts at {next_start:.3f}s before the current "
                    f"scene ends at {final_word_end:.3f}s."
                )
            end = next_start
            if audio_path is not None:
                try:
                    end = resolve_audio_boundary(
                        audio_path,
                        final_word_end=final_word_end,
                        next_word_start=next_start,
                    )
                except ValueError as exc:
                    if isinstance(exc, AudioDecodeError):
                        end = next_start
                    else:
                        raise
        else:
            end = (
                narration_duration_sec
                if narration_duration_sec is not None
                else final_word_end
            )
        ends.append(end)
        if index + 1 < len(starts) and audio_path is not None:
            starts[index + 1] = end

    result: list[SceneAlignment] = []
    for index, (scene, word_offset, scene_timestamps) in enumerate(scene_ranges):
        start = starts[index]
        end = ends[index]
        result.append(
            SceneAlignment(
                id=str(scene["id"]),
                word_offset=word_offset,
                word_count=len(scene_timestamps),
                start_time_sec=start,
                end_time_sec=end,
                duration_sec=end - start,
            )
        )
    return result


def _decoded_audio_mono(path: Path, sample_rate: int = 44100) -> np.ndarray:
    process = subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-i",
            str(path),
            "-f",
            "f32le",
            "-ac",
            "1",
            "-ar",
            str(sample_rate),
            "pipe:1",
        ],
        capture_output=True,
        check=False,
    )
    if process.returncode != 0 or not process.stdout:
        raise AudioDecodeError(
            f"Could not decode narration audio for scene-boundary analysis: {path}"
        )
    samples = np.frombuffer(process.stdout, dtype=np.float32)
    if samples.size == 0:
        raise AudioDecodeError(f"Decoded narration audio is empty: {path}")
    return samples


def _frame_energy(
    samples: np.ndarray,
    start: int,
    end: int,
    sample_rate: int,
) -> tuple[float, float]:
    frame = samples[start:end]
    if len(frame) == 0:
        return 0.0, 0.0
    window = np.hanning(len(frame))
    spectrum = np.abs(np.fft.rfft(frame * window))
    frequencies = np.fft.rfftfreq(len(frame), 1.0 / sample_rate)
    high = spectrum[frequencies >= 4000.0]
    high_power = float(np.sum(high * high)) / max(1, len(frame) ** 2)
    return float(np.sqrt(np.mean(frame * frame))), float(np.sqrt(high_power))


def resolve_audio_boundary(
    audio_path: Path,
    *,
    final_word_end: float,
    next_word_start: float,
    sample_rate: int = 44100,
) -> float:
    """Find a quiet, contiguous split after a word's acoustic tail.

    The timestamp boundary remains the safe fallback when no distinct quiet
    interval can be established. This avoids inventing padding or moving the
    incoming scene without acoustic evidence.
    """
    if next_word_start <= final_word_end:
        return next_word_start
    samples = _decoded_audio_mono(audio_path, sample_rate)
    frame_size = max(1, round(BOUNDARY_FRAME_SEC * sample_rate))
    min_frames = max(1, round(BOUNDARY_MIN_QUIET_SEC / BOUNDARY_FRAME_SEC))
    search_start = max(0.0, final_word_end)
    search_end = min(
        len(samples) / sample_rate,
        next_word_start + BOUNDARY_SEARCH_AFTER_NEXT_START_SEC,
    )
    starts = range(
        round(search_start * sample_rate),
        max(round(search_start * sample_rate), round(search_end * sample_rate) - frame_size + 1),
        frame_size,
    )
    frames: list[tuple[float, bool]] = []
    for start in starts:
        rms, high_freq_rms = _frame_energy(
            samples,
            start,
            min(len(samples), start + frame_size),
            sample_rate,
        )
        frames.append(
            (
                start / sample_rate,
                rms <= BOUNDARY_QUIET_RMS
                and high_freq_rms <= BOUNDARY_QUIET_HIGH_FREQ_RMS,
            )
        )
    for index in range(len(frames) - min_frames + 1):
        if not all(quiet for _, quiet in frames[index : index + min_frames]):
            continue
        boundary = frames[index][0]
        if any(not quiet for _, quiet in frames[index + min_frames :]):
            return boundary
    return next_word_start
