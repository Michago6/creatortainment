"""Offline tests for animated visual assets in MoviePy and storyboards."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from moviepy import VideoFileClip
from PIL import Image

import creatortainment.render.mock as storyboard_renderer
from creatortainment.render.mock import render_storyboard
from creatortainment.render.moviepy_scene import build_static_scene_clip
from creatortainment.render.visual_assets import first_frame_image, load_visual_clip


ROOT = Path(__file__).parents[1]
ASSETS = ROOT / "assets"
IMAGES = ASSETS / "testing/images"
BACKGROUNDS = ASSETS / "testing/backgrounds"


def _script() -> dict:
    return json.loads(
        (ROOT / "scripts/testing_scripts/example_script.json").read_text(
            encoding="utf-8"
        )
    )


def _scene_script(asset_path: str, *, element: bool = False) -> dict:
    script = _script()
    registry = script["asset_registry"]
    registry["test_visual"] = {"path": asset_path, "generate": None}
    scene = script["scenes"][0]
    if element:
        scene["elements"] = [dict(scene["elements"][0], asset="test_visual")]
    else:
        scene["bg"] = "test_visual"
    return script


def test_short_gif_loops_to_exact_duration() -> None:
    clip = load_visual_clip(IMAGES / "test_animation_short.gif", 2.5)
    try:
        assert clip.duration == 2.5
        assert clip.audio is None
        assert not np.array_equal(clip.get_frame(0.1), clip.get_frame(1.1))
    finally:
        clip.close()


def test_short_mp4_loops_to_exact_duration_and_has_no_audio() -> None:
    clip = load_visual_clip(IMAGES / "test_animation_short.mp4", 2.5)
    try:
        assert clip.duration == 2.5
        assert clip.audio is None
        assert clip.get_frame(2.4).shape[:2] == (470, 854)
    finally:
        clip.close()


def test_long_gif_is_trimmed_to_exact_duration() -> None:
    clip = load_visual_clip(IMAGES / "test_animation_long.gif", 2.5)
    try:
        assert clip.duration == 2.5
        assert clip.audio is None
    finally:
        clip.close()


def test_long_mp4_is_trimmed_to_exact_duration() -> None:
    clip = load_visual_clip(IMAGES / "test_animation_long.mp4", 2.5)
    try:
        assert clip.duration == 2.5
        assert clip.audio is None
    finally:
        clip.close()


def test_animated_gif_and_mp4_backgrounds_cover_fit_and_duration() -> None:
    for path in (
        BACKGROUNDS / "test_animated_background_short.gif",
        BACKGROUNDS / "test_animated_background_long.mp4",
    ):
        script = _scene_script(f"assets/testing/backgrounds/{path.name}")
        clip = build_static_scene_clip(
            script,
            script["scenes"][0],
            {"duration_sec": 2.5},
            ASSETS,
        )
        try:
            assert clip.duration == 2.5
            assert clip.size == tuple(script["project"]["resolution"])
            assert clip.get_frame(0).shape[:2] == (1920, 1080)
        finally:
            clip.close()


def test_animated_gif_and_mp4_static_elements_preserve_size_anchor_and_opacity() -> None:
    for path in (
        IMAGES / "test_animation_short.gif",
        IMAGES / "test_animation_short.mp4",
    ):
        script = _scene_script(f"assets/testing/images/{path.name}", element=True)
        clip = build_static_scene_clip(
            script,
            script["scenes"][0],
            {"duration_sec": 2.5},
            ASSETS,
        )
        try:
            element_layer = clip.clips[1]
            assert clip.duration == 2.5
            assert element_layer.pos(0) == (
                round(540 - element_layer.w / 2),
                round(1750 - element_layer.h),
            )
            assert element_layer.get_frame(0).shape[0] == round(0.32 * 1920)
        finally:
            clip.close()


def test_keyframe_driven_animated_elements_keep_transformations() -> None:
    script = _script()
    script["asset_registry"]["test_visual"] = {
        "path": "assets/testing/images/test_animation_short.mp4",
        "generate": None,
    }
    scene = script["scenes"][2]
    element = next(item for item in scene["elements"] if item["id"] == "main_character")
    element["asset"] = "test_visual"
    manifest = json.loads(
        (ROOT / "projects/understanding_gpu_architecture/build_manifests/example_script.json").read_text(
            encoding="utf-8"
        )
    )
    clip = build_static_scene_clip(
        script,
        scene,
        manifest["scenes"][2],
        ASSETS,
        manifest,
    )
    try:
        element_layer = clip.clips[1]
        assert clip.duration == manifest["scenes"][2]["duration_sec"]
        assert element_layer.pos(0.1) != element_layer.pos(clip.duration - 0.1)
    finally:
        clip.close()


def test_storyboard_uses_first_frame_for_gif_and_mp4(
    tmp_path: Path,
    monkeypatch,
) -> None:
    requested: list[Path] = []
    original = storyboard_renderer.first_frame_image

    def tracked_first_frame(path: Path) -> Image.Image:
        requested.append(path)
        return original(path)

    monkeypatch.setattr(storyboard_renderer, "first_frame_image", tracked_first_frame)
    for path in (
        IMAGES / "test_animation_short.gif",
        IMAGES / "test_animation_short.mp4",
    ):
        script = _scene_script(f"assets/testing/images/{path.name}", element=True)
        output = tmp_path / f"{path.stem}.png"
        render_storyboard(script, ASSETS, output)
        assert output.is_file()
        with Image.open(output) as storyboard:
            assert storyboard.format == "PNG"
        with VideoFileClip(str(path), audio=False) as source:
            expected = first_frame_image(path)
            actual = np.asarray(expected)
            assert actual.shape[:2] == (source.h, source.w)
    assert [
        path
        for path in requested
        if path in {IMAGES / "test_animation_short.gif", IMAGES / "test_animation_short.mp4"}
    ] == [
        IMAGES / "test_animation_short.gif",
        IMAGES / "test_animation_short.mp4",
    ]
