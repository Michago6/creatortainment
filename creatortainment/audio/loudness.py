"""Integrated loudness measurement and narration-relative music gain."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import numpy as np
import pyloudnorm as pyln
import soundfile as sf


def measure_loudness(audio_file_path: Path) -> float:
    """Measure integrated loudness in LUFS for an audio file."""
    samples, sample_rate = sf.read(str(audio_file_path), always_2d=True)
    if samples.size == 0:
        raise ValueError(f"Audio file is empty: {audio_file_path}")
    samples = np.asarray(samples, dtype=np.float64)
    meter = pyln.Meter(sample_rate)
    return float(meter.integrated_loudness(samples))


def compute_duck_gain(
    narration_loudness: float,
    music_loudness: float,
    duck_pct: float,
) -> float:
    """Return linear gain placing music at duck_pct of narration loudness."""
    if not math.isfinite(narration_loudness) or not math.isfinite(music_loudness):
        raise ValueError("Audio loudness values must be finite.")
    if not math.isfinite(duck_pct) or duck_pct <= 0.0 or duck_pct > 1.0:
        raise ValueError("duck_pct must be greater than 0 and at most 1.")
    target_music_loudness = narration_loudness + 20.0 * math.log10(duck_pct)
    return float(10.0 ** ((target_music_loudness - music_loudness) / 20.0))


class LoudnessCache:
    """Cache measured loudness until a file's size or mtime changes."""

    def __init__(self) -> None:
        self._values: dict[Path, tuple[int, int, float]] = {}

    def measure(self, audio_file_path: Path) -> float:
        path = Path(audio_file_path)
        stat = path.stat()
        signature = (stat.st_size, stat.st_mtime_ns)
        cached = self._values.get(path)
        if cached is not None and cached[:2] == signature:
            return cached[2]
        loudness = measure_loudness(path)
        self._values[path] = (*signature, loudness)
        return loudness
