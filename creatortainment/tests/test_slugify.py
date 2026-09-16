"""Tests deterministic, Unicode-aware project folder slug generation."""

from creatortainment.project_identity import slugify


def test_slugify_collapses_punctuation_and_whitespace() -> None:
    """Punctuation and whitespace become one trimmed underscore separator."""
    assert slugify("  GPU: Architecture!!!  ") == "gpu_architecture"


def test_slugify_preserves_unicode_letters() -> None:
    """Unicode letters remain usable in stable project identities."""
    assert slugify("Café — 東京") == "café_東京"


def test_slugify_limits_long_titles() -> None:
    """Very long titles receive a deterministic bounded slug."""
    slug = slugify("A" * 200)
    assert len(slug) == 80


def test_slugify_empty_title_has_fallback() -> None:
    """Titles with no word characters use the stable fallback identity."""
    assert slugify("!!!") == "untitled_project"
