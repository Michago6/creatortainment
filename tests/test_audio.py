"""Tests canonical tokenization, scene alignment, and narration cache behavior."""

from __future__ import annotations

import copy
import json
from pathlib import Path

from creatortainment.audio.alignment import align_scenes
from creatortainment.audio.elevenlabs_client import NarrationResult, WordTimestamp
from creatortainment.audio.manifest import build_manifest
from creatortainment.audio.tokenize import tokenize


ROOT = Path(__file__).parents[1]
SCRIPT_PATH = ROOT / "scripts/testing_scripts/example_script.json"
FIXTURE_PATH = ROOT / "tests/fixtures/mock_elevenlabs_response.json"


def test_tokenize_preserves_word_boundaries() -> None:
    """Whitespace normalization preserves punctuation-attached tokens."""
    assert tokenize("  GPU,   we're state-of-the-art  ") == [
        "GPU,",
        "we're",
        "state-of-the-art",
    ]
    assert tokenize("") == []
    assert tokenize("single") == ["single"]


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
    assert aligned[0].end_time_sec == 4.75
    assert aligned[1].start_time_sec == 4.8
    assert aligned[2].start_time_sec == 7.8


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
