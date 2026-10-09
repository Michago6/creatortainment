"""Offline tests for ElevenLabs response parsing and tokenizer alignment."""

import pytest

from creatortainment.audio.elevenlabs_client import (
    ElevenLabsNarrationClient,
    NarrationSegmentResult,
    WordTimestamp,
    _word_timestamps_from_alignment,
)
from creatortainment.schema.models import NarrationSegment


def test_character_alignment_becomes_word_timestamps() -> None:
    """Character-level timing is grouped into punctuation-preserving words."""
    text = "GPU, works."
    alignment = {
        "characters": list(text),
        "character_start_times_seconds": [index * 0.1 for index in range(len(text))],
        "character_end_times_seconds": [(index + 1) * 0.1 for index in range(len(text))],
    }
    result = _word_timestamps_from_alignment(text, alignment)
    assert [item.word for item in result] == ["GPU,", "works."]
    assert result[0].start == 0.0
    assert result[0].end == 0.4


def test_audio_tags_are_excluded_but_source_timing_gaps_are_preserved() -> None:
    text = "[whispers] Hello [nervous laugh] there."
    alignment = {
        "characters": list(text),
        "character_start_times_seconds": [index * 0.1 for index in range(len(text))],
        "character_end_times_seconds": [(index + 1) * 0.1 for index in range(len(text))],
    }

    result = _word_timestamps_from_alignment(text, alignment)

    assert [item.word for item in result] == ["Hello", "there."]
    assert result[0].start == 1.1
    assert result[1].start == pytest.approx(3.3)


class FakeSegmentClient(ElevenLabsNarrationClient):
    def __init__(self) -> None:
        super().__init__("offline", voice_id="default", model_id="test")
        self.calls: list[tuple[str, str]] = []

    def _synthesize_segment(
        self,
        segment: NarrationSegment,
        *,
        voice_id: str,
    ) -> NarrationSegmentResult:
        self.calls.append((segment.text, voice_id))
        return NarrationSegmentResult(
            segment=segment,
            audio_bytes=segment.text.encode(),
            word_timestamps=[
                WordTimestamp(
                    word=word,
                    start=index * 0.5,
                    end=index * 0.5 + 0.4,
                    segment_id=segment.id,
                    scene_id=segment.scene_id,
                    voice_id=segment.voice_id,
                    segment_word_index=index,
                )
                for index, word in enumerate(segment.text.split())
            ],
        )


def test_sequential_segments_use_effective_voice_and_retain_segment_word_metadata() -> None:
    segments = [
        NarrationSegment("one", "scene-1", "Hello there.", "voice-a", 0, 0),
        NarrationSegment("two", "scene-1", "Hi!", "voice-b", 0, 1),
    ]
    client = FakeSegmentClient()

    results = client.synthesize_segments(segments)

    assert client.calls == [("Hello there.", "voice-a"), ("Hi!", "voice-b")]
    assert [(item.segment.id, item.segment.voice_id) for item in results] == [
        ("one", "voice-a"),
        ("two", "voice-b"),
    ]
    assert results[0].word_timestamps[1].segment_word_index == 1
    assert results[0].word_timestamps[1].scene_id == "scene-1"
    assert results[0].word_timestamps[1].voice_id == "voice-a"


def test_segment_word_timestamp_serialization_preserves_legacy_shape_when_unannotated() -> None:
    assert WordTimestamp("Hello", 0.0, 0.5).to_dict() == {
        "word": "Hello",
        "start": 0.0,
        "end": 0.5,
    }
