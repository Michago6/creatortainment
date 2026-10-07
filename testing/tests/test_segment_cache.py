from pathlib import Path

from creatortainment.audio.elevenlabs_client import NarrationSegmentResult, WordTimestamp
from creatortainment.audio.segment_cache import (
    find_cached_segment,
    write_cached_segment,
)
from creatortainment.schema.models import NarrationSegment


def test_unchanged_segment_is_reused_from_cache(tmp_path: Path) -> None:
    segment = NarrationSegment("segment-1", "scene-1", "Hello.", "voice-a", 0, 0)
    result = NarrationSegmentResult(
        segment=segment,
        audio_bytes=b"audio",
        word_timestamps=[
            WordTimestamp(
                "Hello.",
                0.0,
                0.5,
                segment_id=segment.id,
                scene_id=segment.scene_id,
                voice_id=segment.voice_id,
                segment_word_index=0,
            )
        ],
    )

    write_cached_segment(tmp_path, result, "model")
    cached = find_cached_segment(tmp_path, segment, "model")

    assert cached is not None
    assert cached.audio_bytes == b"audio"
    assert cached.word_timestamps[0].segment_id == "segment-1"
    assert cached.word_timestamps[0].voice_id == "voice-a"


def test_segment_cache_key_changes_when_voice_or_text_changes(tmp_path: Path) -> None:
    original = NarrationSegment("segment-1", "scene-1", "Hello.", "voice-a", 0, 0)
    changed_voice = NarrationSegment("segment-1", "scene-1", "Hello.", "voice-b", 0, 0)
    changed_text = NarrationSegment("segment-1", "scene-1", "Goodbye.", "voice-a", 0, 0)
    result = NarrationSegmentResult(original, b"audio", [WordTimestamp("Hello.", 0.0, 0.5)])

    write_cached_segment(tmp_path, result, "model")

    assert find_cached_segment(tmp_path, original, "model") is not None
    assert find_cached_segment(tmp_path, changed_voice, "model") is None
    assert find_cached_segment(tmp_path, changed_text, "model") is None
