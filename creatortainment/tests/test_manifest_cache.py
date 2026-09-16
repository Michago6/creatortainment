"""Tests that narration caching includes both wording and the selected TTS model."""

from creatortainment.audio.manifest import narration_hash


def test_narration_hash_changes_when_model_changes() -> None:
    """Changing tts_model invalidates the full-video narration cache."""
    script = {"project": {"tts_model": "eleven_flash_v2_5"}, "scenes": [{"narration_text": "Hello."}]}
    changed = {"project": {"tts_model": "eleven_multilingual_v2"}, "scenes": [{"narration_text": "Hello."}]}
    assert narration_hash(script) != narration_hash(changed)


def test_narration_hash_changes_when_text_changes() -> None:
    """Changing any scene narration invalidates the full-video narration cache."""
    script = {"project": {"tts_model": "eleven_flash_v2_5"}, "scenes": [{"narration_text": "Hello."}]}
    changed = {"project": {"tts_model": "eleven_flash_v2_5"}, "scenes": [{"narration_text": "Goodbye."}]}
    assert narration_hash(script) != narration_hash(changed)
