"""The only ElevenLabs SDK integration point."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from .tokenize import tokenize


@dataclass(frozen=True)
class WordTimestamp:
    word: str
    start: float
    end: float

    def to_dict(self) -> dict[str, Any]:
        return {"word": self.word, "start": self.start, "end": self.end}


@dataclass(frozen=True)
class NarrationResult:
    audio_bytes: bytes
    word_timestamps: list[WordTimestamp]
    pause_before_sec: list[float]


class NarrationClient(Protocol):
    def synthesize(self, scenes: list[dict[str, Any]]) -> NarrationResult:
        ...


def narration_text_and_pauses(
    scenes: list[dict[str, Any]], pause_default_sec: float = 0.3
) -> tuple[str, list[float]]:
    text_parts: list[str] = []
    pauses: list[float] = []
    for scene in scenes:
        text_parts.append(scene["narration_text"].strip())
        pauses.append(float(scene.get("pause_before_sec", pause_default_sec)))
    return " ".join(text_parts), pauses


class ElevenLabsNarrationClient:
    """Generate one full-video narration request and alignment response."""

    def __init__(
        self,
        api_key: str,
        *,
        voice_id: str,
        model_id: str = "eleven_multilingual_v2",
    ) -> None:
        self.api_key = api_key
        self.voice_id = voice_id
        self.model_id = model_id

    def synthesize(self, scenes: list[dict[str, Any]]) -> NarrationResult:
        text, pauses = narration_text_and_pauses(scenes)
        try:
            from elevenlabs.client import ElevenLabs
        except ImportError as exc:
            raise RuntimeError(
                "The ElevenLabs SDK is required for live narration. "
                "Install the full extras before using the live client."
            ) from exc
        client = ElevenLabs(api_key=self.api_key)
        response = client.text_to_speech.convert_with_timestamps(
            voice_id=self.voice_id,
            model_id=self.model_id,
            text=text,
            output_format="mp3_44100_128",
        )
        if isinstance(response, dict):
            audio_base64 = response.get("audio_base64")
            alignment = response.get("alignment")
        else:
            audio_base64 = getattr(response, "audio_base64", None)
            alignment = getattr(response, "alignment", None)
        if not isinstance(audio_base64, str) or alignment is None:
            raise RuntimeError("ElevenLabs returned no audio bytes or character alignment.")
        import base64

        audio_bytes = base64.b64decode(audio_base64)
        timestamps = _word_timestamps_from_alignment(text, alignment)
        return NarrationResult(audio_bytes, timestamps, pauses)


def _word_timestamps_from_alignment(text: str, alignment: Any) -> list[WordTimestamp]:
    def value(name: str) -> Any:
        if isinstance(alignment, dict):
            return alignment.get(name)
        return getattr(alignment, name, None)

    characters = value("characters")
    starts = value("character_start_times_seconds")
    ends = value("character_end_times_seconds")
    if not all(isinstance(item, list) for item in (characters, starts, ends)):
        raise RuntimeError("ElevenLabs alignment has an unsupported shape.")
    if not (len(characters) == len(starts) == len(ends)):
        raise RuntimeError("ElevenLabs alignment arrays have different lengths.")
    tokens = tokenize(text)
    result: list[WordTimestamp] = []
    cursor = 0
    for token in tokens:
        cursor = text.find(token, cursor)
        if cursor < 0 or cursor + len(token) > len(characters):
            raise RuntimeError(f"Could not map aligned token {token!r} to source text.")
        end_cursor = cursor + len(token)
        result.append(
            WordTimestamp(
                word=token,
                start=float(starts[cursor]),
                end=float(ends[end_cursor - 1]),
            )
        )
        cursor = end_cursor
    return result
