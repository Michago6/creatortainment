"""The only ElevenLabs SDK integration point."""

from __future__ import annotations

import traceback
from dataclasses import dataclass
from pathlib import Path
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
        model_id: str = "eleven_flash_v2_5",
        debug_log: Path | None = None,
    ) -> None:
        self.api_key = api_key
        self.voice_id = voice_id
        self.model_id = model_id
        self.debug_log = debug_log

    def _debug(self, message: str) -> None:
        if self.debug_log is not None:
            self.debug_log.parent.mkdir(parents=True, exist_ok=True)
            with self.debug_log.open("a", encoding="utf-8") as handle:
                handle.write(f"{message}\n")

    def synthesize(self, scenes: list[dict[str, Any]]) -> NarrationResult:
        text, pauses = narration_text_and_pauses(scenes)
        self._debug(
            f"request text_chars={len(text)} word_count={len(tokenize(text))} "
            f"voice_id={self.voice_id!r} model_id={self.model_id!r} "
            f"pause_count={len(pauses)}"
        )
        if not self.api_key.strip():
            raise RuntimeError("ELEVENLABS_API_KEY is required for real narration generation.")
        try:
            from elevenlabs.client import ElevenLabs
        except ImportError as exc:
            raise RuntimeError(
                "The ElevenLabs SDK is required for live narration. "
                "Install the full extras before using the live client."
            ) from exc
        client = ElevenLabs(api_key=self.api_key)
        try:
            response = client.text_to_speech.convert_with_timestamps(
                voice_id=self.voice_id,
                model_id=self.model_id,
                text=text,
                output_format="mp3_44100_128",
            )
        except Exception as exc:
            self._debug(f"request failed type={type(exc).__name__} message={exc}")
            self._debug(traceback.format_exc())
            raise RuntimeError(f"ElevenLabs request failed: {exc}") from exc

        if isinstance(response, dict):
            audio_base64 = response.get("audio_base64", response.get("audio_base_64"))
            alignment = response.get("alignment") or response.get("normalized_alignment")
            response_fields = sorted(response)
        else:
            audio_base64 = getattr(response, "audio_base64", None)
            if audio_base64 is None:
                audio_base64 = getattr(response, "audio_base_64", None)
            alignment = getattr(response, "alignment", None)
            if alignment is None:
                alignment = getattr(response, "normalized_alignment", None)
            response_fields = [
                name for name in ("audio_base64", "audio_base_64", "alignment", "normalized_alignment")
                if hasattr(response, name)
            ]
        self._debug(
            f"response type={type(response).__name__} fields={response_fields} "
            f"audio_base64_type={type(audio_base64).__name__} "
            f"audio_base64_chars={len(audio_base64) if isinstance(audio_base64, str) else 0} "
            f"alignment_type={type(alignment).__name__ if alignment is not None else 'None'}"
        )
        if not isinstance(audio_base64, str) or alignment is None:
            raise RuntimeError(
                "ElevenLabs returned no usable audio bytes or character alignment. "
                f"Response type: {type(response).__name__}; fields: {response_fields}."
            )
        import base64

        try:
            audio_bytes = base64.b64decode(audio_base64, validate=True)
            timestamps = _word_timestamps_from_alignment(text, alignment)
        except Exception as exc:
            self._debug(f"response parsing failed type={type(exc).__name__} message={exc}")
            self._debug(traceback.format_exc())
            raise RuntimeError(f"Could not parse ElevenLabs audio/alignment response: {exc}") from exc
        self._debug(
            f"parsed audio_bytes={len(audio_bytes)} word_timestamps={len(timestamps)}"
        )
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
