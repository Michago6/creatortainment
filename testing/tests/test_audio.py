"""Tests canonical tokenization, scene alignment, and narration cache behavior."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import numpy as np
import pytest
from moviepy import AudioClip, AudioFileClip, CompositeAudioClip

from creatortainment.audio.alignment import align_scenes
from creatortainment.audio.elevenlabs_client import NarrationResult, WordTimestamp
from creatortainment.audio.manifest import (
    build_manifest,
    narration_hash,
    refresh_cached_manifest_scenes,
)
from creatortainment.audio.tokenize import spoken_words, tokenize


ROOT = Path(__file__).parents[2]
SCRIPT_PATH = ROOT / "testing/scripts/example_script.json"
FIXTURE_PATH = ROOT / "testing/tests/fixtures/mock_elevenlabs_response.json"


def test_tokenize_preserves_word_boundaries() -> None:
    """Whitespace normalization preserves punctuation-attached tokens."""
    assert tokenize("  GPU,   we're state-of-the-art  ") == [
        "GPU,",
        "we're",
        "state-of-the-art",
    ]
    assert tokenize("") == []
    assert tokenize("single") == ["single"]


def test_spoken_words_exclude_leading_embedded_trailing_and_multiword_tags() -> None:
    assert spoken_words(
        "[curious] Does math scare you? [nervous laugh] Really? [beat]"
    ) == ["Does", "math", "scare", "you?", "Really?"]


def _script() -> dict:
    return json.loads(SCRIPT_PATH.read_text(encoding="utf-8"))


def _timestamps() -> list[dict]:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))["word_timestamps"]


def test_alignment_slices_example_scenes() -> None:
    """The example script receives correct cumulative scene offsets and timing."""
    script = _script()
    aligned = align_scenes(script["scenes"], _timestamps())
    assert [(item.word_offset, item.word_count) for item in aligned] == [
        (0, 16),
        (16, 10),
        (26, 16),
    ]
    assert aligned[0].start_time_sec == 0.0
    assert aligned[0].end_time_sec == 4.8
    assert aligned[1].start_time_sec == 4.8
    assert aligned[1].end_time_sec == 7.8
    assert aligned[2].start_time_sec == 7.8


def test_alignment_assigns_positive_gap_to_preceding_scene() -> None:
    scenes = [
        {"id": "one", "narration_text": "Alpha."},
        {"id": "two", "narration_text": "Beta."},
    ]
    timestamps = [
        {"word": "Alpha.", "start": 1.0, "end": 1.4},
        {"word": "Beta.", "start": 1.55, "end": 1.9},
    ]

    aligned = align_scenes(scenes, timestamps)

    assert aligned[0].start_time_sec == 1.0
    assert aligned[0].end_time_sec == 1.55
    assert aligned[0].duration_sec == pytest.approx(0.55)
    assert aligned[1].start_time_sec == 1.55
    assert aligned[1].end_time_sec == 1.9


def test_alignment_rejects_overlapping_scene_ranges() -> None:
    scenes = [
        {"id": "one", "narration_text": "Alpha."},
        {"id": "two", "narration_text": "Beta."},
    ]
    timestamps = [
        {"word": "Alpha.", "start": 1.0, "end": 1.6},
        {"word": "Beta.", "start": 1.5, "end": 1.9},
    ]

    with pytest.raises(ValueError, match="overlaps scenes"):
        align_scenes(scenes, timestamps)


def test_alignment_preserves_zero_gap_and_final_scene_end() -> None:
    scenes = [
        {
            "id": "one",
            "narration_text": "Alpha.",
            "pause_before_sec": 2.0,
            "extra_duration_sec": 4.0,
        },
        {"id": "two", "narration_text": "Beta."},
    ]
    aligned = align_scenes(
        scenes,
        [
            {"word": "Alpha.", "start": 1.0, "end": 1.5},
            {"word": "Beta.", "start": 1.5, "end": 1.9},
        ],
    )

    assert aligned[0].end_time_sec == aligned[1].start_time_sec == 1.5
    assert aligned[0].duration_sec == pytest.approx(0.5)
    assert aligned[1].end_time_sec == pytest.approx(1.9)


def test_alignment_gap_audio_is_retained_once_in_combined_slices(tmp_path: Path) -> None:
    sample_rate = 44100
    gap_start = 0.4
    next_start = 0.55

    def marker_frame(t: float | np.ndarray) -> np.ndarray:
        times = np.asarray(t)
        values = np.where(
            times < gap_start,
            0.2,
            np.where(times < next_start, 0.6, 0.0),
        )
        if times.ndim == 0:
            return np.array([float(values), float(values)])
        return np.column_stack((values, values))

    source = AudioClip(marker_frame, duration=0.8, fps=sample_rate)
    source_path = tmp_path / "source.wav"
    source.write_audiofile(str(source_path), fps=sample_rate, codec="pcm_s16le", logger=None)
    source.close()

    scenes = [
        {"id": "one", "narration_text": "Alpha."},
        {"id": "two", "narration_text": "Beta."},
    ]
    aligned = align_scenes(
        scenes,
        [
            {"word": "Alpha.", "start": 0.0, "end": gap_start},
            {"word": "Beta.", "start": next_start, "end": 0.8},
        ],
    )
    audio = AudioFileClip(str(source_path))
    first = audio.subclipped(aligned[0].start_time_sec, aligned[0].end_time_sec)
    second = audio.subclipped(aligned[1].start_time_sec, aligned[1].end_time_sec)
    combined = CompositeAudioClip([first.with_start(0), second.with_start(first.duration)])
    try:
        first_gap_sample = float(combined.get_frame(gap_start + 0.05)[0])
        second_start_sample = float(combined.get_frame(first.duration)[0])
        assert first_gap_sample == pytest.approx(0.6, abs=0.02)
        assert second_start_sample == pytest.approx(0.0, abs=0.02)
        assert first.duration == pytest.approx(next_start)
        assert combined.clips[1].start == pytest.approx(first.duration)
    finally:
        combined.close()
        second.close()
        first.close()
        audio.close()


class CountingClient:
    def __init__(self, timestamps: list[dict]) -> None:
        self.calls = 0
        self.timestamps = timestamps

    def synthesize(self, scenes: list[dict]) -> NarrationResult:
        self.calls += 1
        expected = sum(len(scene["narration_text"].split()) for scene in scenes)
        timestamps = list(self.timestamps)
        while len(timestamps) < expected:
            index = len(timestamps)
            timestamps.append({"word": "Again.", "start": index * 0.3, "end": index * 0.3 + 0.25})
        return NarrationResult(
            audio_bytes=b"audio",
            word_timestamps=[WordTimestamp(**item) for item in timestamps[:expected]],
            pause_before_sec=[],
        )


def test_manifest_cache_hit_and_narration_cache_miss(tmp_path: Path) -> None:
    """Matching narration reuses the cache while edited text synthesizes again."""
    script = _script()
    client = CountingClient(_timestamps())
    path = tmp_path / "build_manifest.json"
    _, cached = build_manifest(script, path, client)
    assert cached is False
    _, cached = build_manifest(script, path, client)
    assert cached is True
    assert client.calls == 1

    changed = copy.deepcopy(script)
    changed["scenes"][0]["narration_text"] += " Again."
    _, cached = build_manifest(changed, path, client)
    assert cached is False
    assert client.calls == 2


def _cached_manifest_script() -> dict:
    return {
        "project": {"tts_model": "eleven_flash_v2_5"},
        "scenes": [
            {"id": "one", "narration_text": "Alpha beta."},
            {"id": "two", "narration_text": "Gamma delta."},
        ],
    }


def _write_cached_audio(path: Path) -> None:
    audio = AudioClip(lambda t: np.array([0.1, 0.1]), duration=2.0, fps=44100)
    try:
        audio.write_audiofile(str(path), fps=44100, codec="pcm_s16le", logger=None)
    finally:
        audio.close()


def _cached_manifest(script: dict, audio_path: Path) -> dict:
    timestamps = [
        {"word": "Alpha", "start": 0.0, "end": 0.3},
        {"word": "beta.", "start": 0.4, "end": 0.7},
        {"word": "Gamma", "start": 0.8, "end": 1.1},
        {"word": "delta.", "start": 1.2, "end": 1.5},
    ]
    return {
        "narration_hash": narration_hash(script),
        "narration_audio_path": str(audio_path),
        "word_timestamps": timestamps,
        "scenes": [
            {
                "id": "one",
                "word_offset": 0,
                "word_count": 2,
                "start_time_sec": 0.0,
                "end_time_sec": 0.8,
                "duration_sec": 0.8,
            },
            {
                "id": "two",
                "word_offset": 2,
                "word_count": 2,
                "start_time_sec": 0.8,
                "end_time_sec": 1.5,
                "duration_sec": 0.7,
            },
        ],
    }


def test_cached_manifest_resegments_when_scene_count_changes(tmp_path: Path) -> None:
    script = _cached_manifest_script()
    audio_path = tmp_path / "narration.wav"
    _write_cached_audio(audio_path)
    manifest = _cached_manifest(script, audio_path)
    script["scenes"] = [
        {"id": "one", "narration_text": "Alpha"},
        {"id": "two", "narration_text": "beta. Gamma"},
        {"id": "three", "narration_text": "delta."},
    ]
    manifest["narration_hash"] = narration_hash(script)

    changed = refresh_cached_manifest_scenes(
        script,
        manifest,
        tmp_path,
        validate_audio_duration=False,
    )

    assert changed is True
    assert [(item["id"], item["word_count"]) for item in manifest["scenes"]] == [
        ("one", 1),
        ("two", 2),
        ("three", 1),
    ]


def test_cached_manifest_resegments_when_scene_boundaries_change(tmp_path: Path) -> None:
    script = _cached_manifest_script()
    audio_path = tmp_path / "narration.wav"
    _write_cached_audio(audio_path)
    manifest = _cached_manifest(script, audio_path)
    script["scenes"] = [
        {"id": "one", "narration_text": "Alpha beta. Gamma"},
        {"id": "two", "narration_text": "delta."},
    ]
    manifest["narration_hash"] = narration_hash(script)

    changed = refresh_cached_manifest_scenes(
        script,
        manifest,
        tmp_path,
        validate_audio_duration=False,
    )

    assert changed is True
    assert [item["word_offset"] for item in manifest["scenes"]] == [0, 3]
    assert [item["start_time_sec"] for item in manifest["scenes"]] == [0.0, 1.2]


def test_cached_manifest_rejects_changed_narration(tmp_path: Path) -> None:
    script = _cached_manifest_script()
    audio_path = tmp_path / "narration.wav"
    _write_cached_audio(audio_path)
    manifest = _cached_manifest(script, audio_path)
    script["scenes"][0]["narration_text"] = "Changed."

    with pytest.raises(ValueError, match="does not match"):
        refresh_cached_manifest_scenes(script, manifest, tmp_path)


def test_old_tagged_manifest_is_rejected_for_explicit_refresh(tmp_path: Path) -> None:
    script = _cached_manifest_script()
    script["scenes"][0]["narration_text"] = "[whispers] Alpha beta."
    audio_path = tmp_path / "narration.wav"
    _write_cached_audio(audio_path)
    manifest = _cached_manifest(script, audio_path)
    manifest["word_timestamps"][0]["word"] = "[whispers]"

    with pytest.raises(ValueError, match="word timestamp .* does not match"):
        refresh_cached_manifest_scenes(script, manifest, tmp_path)


@pytest.mark.parametrize(
    ("final_end", "should_fail"),
    [(2.049, False), (2.101, True)],
)
def test_cached_audio_duration_uses_bounded_alignment_tolerance(
    tmp_path: Path,
    final_end: float,
    should_fail: bool,
    monkeypatch,
) -> None:
    script = _cached_manifest_script()
    audio_path = tmp_path / "narration.wav"
    _write_cached_audio(audio_path)
    manifest = _cached_manifest(script, audio_path)
    manifest["word_timestamps"][-1]["end"] = final_end
    manifest["scenes"][-1]["end_time_sec"] = final_end
    manifest["scenes"][-1]["duration_sec"] = final_end - 0.8
    class FakeAudio:
        duration = 2.0

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def close(self):
            return None

    monkeypatch.setattr(
        "creatortainment.audio.manifest._segment_audio_duration",
        lambda _path, _fallback: FakeAudio.duration,
    )

    if should_fail:
        with pytest.raises(ValueError, match="audio=|shorter"):
            refresh_cached_manifest_scenes(script, manifest, tmp_path)
    else:
        refresh_cached_manifest_scenes(script, manifest, tmp_path)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda manifest: manifest.update({"word_timestamps": []}),
        lambda manifest: manifest["word_timestamps"][1].update({"word": "wrong"}),
        lambda manifest: manifest.update({"narration_audio_path": "missing.wav"}),
    ],
)
def test_cached_manifest_rejects_invalid_or_missing_narration_data(
    tmp_path: Path,
    mutate,
) -> None:
    script = _cached_manifest_script()
    audio_path = tmp_path / "narration.wav"
    _write_cached_audio(audio_path)
    manifest = _cached_manifest(script, audio_path)
    mutate(manifest)

    with pytest.raises((ValueError, FileNotFoundError)):
        refresh_cached_manifest_scenes(script, manifest, tmp_path)
