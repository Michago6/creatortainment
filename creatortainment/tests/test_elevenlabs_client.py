"""Offline tests for ElevenLabs response parsing and tokenizer alignment."""

from creatortainment.audio.elevenlabs_client import _word_timestamps_from_alignment


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
