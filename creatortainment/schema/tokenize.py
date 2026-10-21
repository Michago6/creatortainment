"""Backward-compatible import for the canonical audio tokenizer."""

from ..audio.tokenize import recognized_audio_tags, spoken_words, tokenize

__all__ = ["recognized_audio_tags", "spoken_words", "tokenize"]
