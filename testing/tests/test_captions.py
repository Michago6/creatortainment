"""Tests caption chunking and active-word resolution against real alignment data."""

from __future__ import annotations

import json
from pathlib import Path

from creatortainment.render.captions import (
    CaptionImageCache,
    highlight_color_for_voice,
    measure_caption_words,
    render_caption_chunk,
    resolve_active_caption,
    resolve_active_caption_track,
    wrap_caption_lines,
)
from creatortainment.render.moviepy_scene import resolve_caption_style


ROOT = Path(__file__).parents[2]


def _script() -> dict:
    """Load the real portrait example script."""
    return json.loads(
        (ROOT / "testing/scripts/example_script.json").read_text(
            encoding="utf-8"
        )
    )


def _manifest() -> dict:
    """Load the real aligned portrait manifest."""
    return json.loads(
        (ROOT / "testing/fixtures/manifests/example_script.json").read_text(
            encoding="utf-8"
        )
    )


def test_chunk_exactly_hits_words_per_chunk() -> None:
    """A chunk closes exactly when it reaches the configured word count."""
    chunks = wrap_caption_lines("one two three four", words_per_chunk=3)
    assert [chunk.words for chunk in chunks] == [
        ("one", "two", "three"),
        ("four",),
    ]


def test_voice_colors_are_deterministic_and_cycle() -> None:
    style = {"highlight_color": ["#a", "#b"]}
    voices = ["voice-a", "voice-b", "voice-c"]
    assert highlight_color_for_voice(style, "voice-a", voices) == "#a"
    assert highlight_color_for_voice(style, "voice-b", voices) == "#b"
    assert highlight_color_for_voice(style, "voice-c", voices) == "#a"
    assert highlight_color_for_voice({"highlight_color": "#gold"}, "voice-a", voices) == "#gold"


def test_caption_track_resolves_its_own_active_word() -> None:
    chunks = wrap_caption_lines("one two", words_per_chunk=3)
    timestamps = [
        {"word": "one", "start": 1.0, "end": 1.3},
        {"word": "two", "start": 1.3, "end": 1.6},
    ]
    assert resolve_active_caption_track(1.1, chunks, timestamps) == (0, 0)
    assert resolve_active_caption_track(1.4, chunks, timestamps) == (0, 1)


def test_character_cap_splits_before_word_limit() -> None:
    """The character safety cap can end a chunk before words_per_chunk."""
    chunks = wrap_caption_lines(
        "short exceptionallylongword final",
        words_per_chunk=3,
        max_chars_per_line=15,
    )
    assert [chunk.words for chunk in chunks] == [
        ("short",),
        ("exceptionallylongword",),
        ("final",),
    ]


def test_rendered_width_falls_back_from_three_words_to_two() -> None:
    chunks = wrap_caption_lines(
        "one two three four",
        words_per_chunk=3,
        style={"font_size": 48, "stroke_width": 3},
        resolution=(480, 800),
    )
    assert [chunk.words for chunk in chunks] == [
        ("one", "two"),
        ("three", "four"),
    ]


def test_rendered_width_falls_back_from_two_words_to_one() -> None:
    chunks = wrap_caption_lines(
        "medium medium final",
        words_per_chunk=2,
        style={"font_size": 48, "stroke_width": 3},
        resolution=(320, 568),
    )
    assert [chunk.words for chunk in chunks] == [
        ("medium",),
        ("medium",),
        ("final",),
    ]


def test_stroke_changes_caption_fit_decision() -> None:
    resolution = (480, 800)
    no_stroke = wrap_caption_lines(
        "one two three",
        style={"font_size": 48, "stroke_width": 0},
        resolution=resolution,
    )
    with_stroke = wrap_caption_lines(
        "one two three",
        style={"font_size": 48, "stroke_width": 3},
        resolution=resolution,
    )
    assert no_stroke[0].words == ("one", "two", "three")
    assert [chunk.words for chunk in with_stroke] == [("one", "two"), ("three",)]


def test_fitting_rendered_captions_stay_inside_horizontal_margins() -> None:
    resolution = (480, 800)
    style = {"font_size": 48, "stroke_width": 3}
    horizontal_margin = max(24, round(resolution[0] * 0.06))
    available_width = resolution[0] - 2 * horizontal_margin
    chunks = wrap_caption_lines(
        "one two three four five",
        style=style,
        resolution=resolution,
    )
    for chunk in chunks:
        rendered = render_caption_chunk(chunk, chunk.word_indices[0], style, resolution)
        assert rendered.image.width <= available_width
        assert rendered.position[0] >= horizontal_margin
        assert rendered.position[0] + rendered.image.width <= resolution[0] - horizontal_margin


def test_oversized_single_word_is_kept_as_one_word_chunk() -> None:
    style = {"font_size": 48, "stroke_width": 3}
    resolution = (320, 568)
    chunks = wrap_caption_lines(
        "exceptionallylongword",
        style=style,
        resolution=resolution,
    )
    rendered_width = measure_caption_words(chunks[0].words, style, resolution).image_size[0]
    assert chunks[0].words == ("exceptionallylongword",)
    assert rendered_width > resolution[0] - 2 * max(24, round(resolution[0] * 0.06))


def test_last_chunk_can_be_shorter_than_word_limit() -> None:
    """A non-divisible word count leaves a shorter final chunk."""
    chunks = wrap_caption_lines("one two three four five", words_per_chunk=3)
    assert chunks[-1].words == ("four", "five")
    assert chunks[-1].word_indices == (3, 4)


def test_active_caption_uses_real_scene_one_alignment() -> None:
    """Active words follow scene one word starts and remain on the final chunk."""
    script = _script()
    manifest = _manifest()
    scene = script["scenes"][0]
    scene_manifest = manifest["scenes"][0]
    style = script["project"]["caption_style"]
    chunks = wrap_caption_lines(
        scene["narration_text"],
        style["words_per_chunk"],
        style["max_chars_per_line"],
    )
    timestamps = manifest["word_timestamps"]
    assert resolve_active_caption(
        scene, timestamps[0]["start"] - 0.01, chunks, timestamps,
        word_offset=scene_manifest["word_offset"],
    ) is None
    assert resolve_active_caption(
        scene, timestamps[0]["start"], chunks, timestamps,
        word_offset=scene_manifest["word_offset"],
    ) == (0, 0)
    assert resolve_active_caption(
        scene, timestamps[2]["start"], chunks, timestamps,
        word_offset=scene_manifest["word_offset"],
    ) == (0, 2)
    assert resolve_active_caption(
        scene, timestamps[3]["start"], chunks, timestamps,
        word_offset=scene_manifest["word_offset"],
    ) == (1, 3)
    assert resolve_active_caption(
        scene, timestamps[15]["end"] + 1.0, chunks, timestamps,
        word_offset=scene_manifest["word_offset"],
    ) == (len(chunks) - 1, 15)


def test_caption_image_cache_hits_for_consecutive_frames() -> None:
    """Repeated frames with the same active word reuse one rendered image."""
    chunk = wrap_caption_lines("Welcome back today", words_per_chunk=3)[0]
    cache = CaptionImageCache(
        {
            "font": "Montserrat-Bold",
            "font_size": 48,
            "color": "#FFFFFF",
            "highlight_color": "#FFD700",
            "stroke_color": "#000000",
            "stroke_width": 3,
            "position": "bottom_center",
        },
        (1080, 1920),
    )

    first = cache.get(chunk, 1)
    second = cache.get(chunk, 1)
    third = cache.get(chunk, 1)

    assert first is second is third
    assert cache.render_count == 1
    assert cache.hit_count == 2
    assert first.image.size[0] > 0
    assert first.image.size[1] > 0
    assert first.position[0] >= 0
    assert first.position[1] >= 0
    assert first.image.getpixel((0, 0))[3] == 0


def test_custom_vertical_position_is_resolution_independent() -> None:
    """The explicit vertical anchor is measured from the top for both orientations."""
    chunk = wrap_caption_lines("caption placement", words_per_chunk=3)[0]
    style = {
        "font_size": 48,
        "color": "#FFFFFF",
        "highlight_color": "#FFD700",
        "stroke_color": "#000000",
        "stroke_width": 3,
        "position": "bottom_center",
        "vertical_position_frac": 0.72,
    }
    for resolution in ((1080, 1920), (1920, 1080)):
        rendered = render_caption_chunk(chunk, 0, style, resolution)
        expected_anchor = round(0.72 * resolution[1])
        assert rendered.position[1] + rendered.image.height == expected_anchor


def test_default_vertical_position_preserves_bottom_margin() -> None:
    """Without the new field, placement remains the existing resolution-aware margin."""
    chunk = wrap_caption_lines("caption placement", words_per_chunk=3)[0]
    rendered = render_caption_chunk(
        chunk,
        0,
        {"font_size": 48, "position": "bottom_center"},
        (1080, 1920),
    )
    bottom_margin = max(24, round(1920 * 0.04))
    assert rendered.position[1] + rendered.image.height == 1920 - bottom_margin


def test_scene_vertical_position_overrides_project_style() -> None:
    """Scene caption settings override the project default through the normal merge."""
    script = {
        "project": {"caption_style": {"vertical_position_frac": 0.2}},
    }
    scene = {
        "narration_text": "caption placement",
        "caption_style": {"vertical_position_frac": 0.72},
    }
    style = resolve_caption_style(script, scene)
    assert style["vertical_position_frac"] == 0.72
    chunk = wrap_caption_lines(scene["narration_text"], words_per_chunk=3)[0]
    rendered = render_caption_chunk(chunk, 0, style, (1920, 1080))
    assert rendered.position[1] + rendered.image.height == round(0.72 * 1080)
