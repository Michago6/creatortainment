"""Backward-compatible import for the canonical audio tokenizer."""

from ..audio.tokenize import spoken_words, tokenize

__all__ = ["spoken_words", "tokenize"]
