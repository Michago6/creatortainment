"""The single canonical narration tokenizer."""

from __future__ import annotations

from dataclasses import dataclass
import re


# ElevenLabs v4 directives are bracketed words/phrases. Restrict the parser to
# directive-shaped content rather than treating arbitrary bracketed prose as a tag.
AUDIO_TAG_PATTERN = re.compile(r"\[(?=[A-Za-z])[A-Za-z][A-Za-z' -]{0,62}\]")
WORD_PATTERN = re.compile(r"\S+")


@dataclass(frozen=True)
class SpokenToken:
    word: str
    start: int
    end: int


def tokenize(text: str) -> list[str]:
    """Split on whitespace only; punctuation remains attached to each token."""
    return text.strip().split()


def spoken_tokens(text: str) -> list[SpokenToken]:
    """Return spoken words and their source spans, excluding v4 directives."""
    tokens: list[SpokenToken] = []
    cursor = 0
    for tag in AUDIO_TAG_PATTERN.finditer(text):
        tokens.extend(
            SpokenToken(
                match.group(),
                cursor + match.start(),
                cursor + match.end(),
            )
            for match in WORD_PATTERN.finditer(text[cursor : tag.start()])
        )
        cursor = tag.end()
    tokens.extend(
        SpokenToken(match.group(), match.start() + cursor, match.end() + cursor)
        for match in WORD_PATTERN.finditer(text[cursor:])
    )
    return tokens


def spoken_words(text: str) -> list[str]:
    return [token.word for token in spoken_tokens(text)]
