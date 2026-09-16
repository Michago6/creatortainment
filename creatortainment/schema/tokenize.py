"""Canonical narration tokenization."""

from __future__ import annotations


def tokenize(text: str) -> list[str]:
    """Split on whitespace only, preserving punctuation attached to words."""
    return text.strip().split()
