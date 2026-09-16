"""The single canonical narration tokenizer."""

from __future__ import annotations


def tokenize(text: str) -> list[str]:
    """Split on whitespace only; punctuation remains attached to each token."""
    return text.strip().split()
