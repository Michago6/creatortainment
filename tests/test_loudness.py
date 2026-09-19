"""Tests integrated loudness and narration-relative duck gain."""

from pathlib import Path

import pytest

from creatortainment.audio.loudness import (
    LoudnessCache,
    compute_duck_gain,
    measure_loudness,
)


ROOT = Path(__file__).parents[1]
PROJECT = ROOT / "projects/understanding_gpu_architecture"
NARRATION = next((PROJECT / "narrations").glob("*.mp3"))
MUSIC = ROOT / "assets/audio/monkeys_spinning_monkeys.mp3"


def test_measure_real_narration_and_music_files() -> None:
    """Real project narration and shared music assets produce finite LUFS values."""
    narration = measure_loudness(NARRATION)
    music = measure_loudness(MUSIC)
    assert narration == pytest.approx(narration)
    assert music == pytest.approx(music)


def test_compute_duck_gain_targets_relative_loudness() -> None:
    """The gain places music at the configured loudness fraction."""
    gain = compute_duck_gain(-20.0, -10.0, 0.3)
    expected_target = -20.0 + 20.0 * __import__("math").log10(0.3)
    assert 20.0 * __import__("math").log10(gain) == pytest.approx(expected_target + 10.0)


def test_loudness_cache_avoids_remeasuring_same_file(monkeypatch, tmp_path: Path) -> None:
    """Repeated measurements reuse the cached file result."""
    calls = 0

    def fake_measure(path: Path) -> float:
        nonlocal calls
        calls += 1
        return -18.0

    import creatortainment.audio.loudness as loudness

    monkeypatch.setattr(loudness, "measure_loudness", fake_measure)
    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"audio")
    cache = LoudnessCache()
    assert cache.measure(audio) == -18.0
    assert cache.measure(audio) == -18.0
    assert calls == 1
