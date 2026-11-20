"""Offline tests for animated visual assets in MoviePy and storyboards."""

from __future__ import annotations

import json
import shutil
import subprocess
import warnings
from pathlib import Path

import numpy as np
from moviepy import VideoFileClip
from PIL import Image

import creatortainment.render.mock as storyboard_renderer
from creatortainment.render.mock import render_storyboard
from creatortainment.render.moviepy_scene import build_static_scene_clip
import creatortainment.render.visual_assets as visual_assets
from creatortainment.render.visual_assets import first_frame_image, load_visual_clip


ROOT = Path(__file__).parents[2]
ASSETS = ROOT / "testing/assets"
PRODUCTION_ASSETS = ASSETS
IMAGES = ASSETS / "images"
BACKGROUNDS = ASSETS / "backgrounds"
PRODUCTION_IMAGES = ASSETS / "images"


def _script() -> dict:
    return json.loads(
        (ROOT / "testing/scripts/example_script.json").read_text(
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


def _vfr_reference_frame(path: Path, index: int, size: tuple[int, int]) -> np.ndarray:
    ffmpeg = shutil.which("ffmpeg")
    assert ffmpeg is not None
    process = subprocess.Popen(
        [
            ffmpeg,
            "-v",
            "error",
            "-i",
            str(path),
            "-vsync",
            "0",
            "-f",
            "image2pipe",
            "-vf",
            f"scale={size[0]}:{size[1]}",
            "-pix_fmt",
            "rgb24",
            "-vcodec",
            "rawvideo",
            "-",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    try:
        frame_size = size[0] * size[1] * 3
        data = process.stdout.read(frame_size * (index + 1))
        assert len(data) >= frame_size * (index + 1)
        frame = np.frombuffer(
            data[-frame_size:], dtype=np.uint8
        ).reshape((size[1], size[0], 3))
        return frame
    finally:
        process.kill()
        process.wait()


def test_short_gif_loops_to_exact_duration() -> None:
    clip = load_visual_clip(IMAGES / "test_animation_short.gif", 2.5)
    try:
        assert clip.duration == 2.5
        assert clip.audio is None
        assert not np.array_equal(clip.get_frame(0.1), clip.get_frame(1.1))
    finally:
        clip.close()


def test_existing_two_frame_gifs_animate_with_pillow_timing() -> None:
    cases = (
        (PRODUCTION_IMAGES / "slay_satisfaction.gif", 0.3),
        (PRODUCTION_IMAGES / "cat_shaking_head_no.gif", 0.12),
    )
    for path, first_frame_duration in cases:
        clip = load_visual_clip(path, 1.2)
        try:
            first = clip.get_frame(first_frame_duration / 2)
            second = clip.get_frame(first_frame_duration + 0.01)
            assert not np.array_equal(first, second)
            assert np.array_equal(
                first,
                clip.get_frame(first_frame_duration * 2 + first_frame_duration / 2),
            )
        finally:
            clip.close()


def test_one_frame_gif_remains_static() -> None:
    clip = load_visual_clip(PRODUCTION_IMAGES / "emoji_saying_but_what_if.gif", 1.2)
    try:
        assert np.array_equal(clip.get_frame(0.0), clip.get_frame(1.0))
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


def test_vfr_source_uses_presentation_timestamps() -> None:
    path = ASSETS / "video/mandelbrot_set_tierlist.mp4"
    timestamps = visual_assets._vfr_frame_timestamps(path)
    assert timestamps is not None
    assert len(timestamps) > 40
    assert any(
        later - earlier > 0.5
        for earlier, later in zip(timestamps, timestamps[1:])
    )

    clip = visual_assets._make_source_times_safe(
        VideoFileClip(str(path), audio=False), path
    )
    try:
        requested_time = 1.0
        expected_frame = visual_assets.bisect_right(timestamps, requested_time) - 1
        expected = _vfr_reference_frame(path, expected_frame, clip.size)
        assert np.array_equal(clip.get_frame(requested_time), expected)
    finally:
        clip.close()


def test_vfr_assets_use_exact_decoded_frames_at_early_middle_and_late_times() -> None:
    cases = (
        "mandelbrot_set_tierlist.mp4",
        "multibrot_tierlist.mp4",
        "newton_tierlist.mp4",
    )
    for filename in cases:
        path = ASSETS / "video" / filename
        timestamps = visual_assets._vfr_frame_timestamps(path)
        assert timestamps is not None
        source = VideoFileClip(str(path), audio=False)
        clip = visual_assets._make_source_times_safe(source, path)
        try:
            for requested_time in (
                timestamps[1] / 2,
                timestamps[len(timestamps) // 2],
                timestamps[-1],
            ):
                index = max(
                    0,
                    min(
                        len(timestamps) - 1,
                        visual_assets.bisect_right(timestamps, requested_time) - 1,
                    ),
                )
                expected = _vfr_reference_frame(path, index, clip.size)
                assert np.array_equal(clip.get_frame(requested_time), expected)
        finally:
            clip.close()


def test_cfr_source_keeps_constant_fps_frame_lookup(monkeypatch) -> None:
    class Reader:
        n_frames = 10

        @staticmethod
        def get_frame_number(time: float) -> int:
            return int(time * 10)

    class Clip:
        fps = 10.0
        reader = Reader()

        def __init__(self) -> None:
            self.frame_function = self._frame
            self.requested: list[float] = []

        def _frame(self, time: float) -> np.ndarray:
            self.requested.append(time)
            return np.zeros((1, 1, 3), dtype=np.uint8)

    source = Clip()
    monkeypatch.setattr(visual_assets, "_vfr_frame_timestamps", lambda _path: None)
    monkeypatch.setattr(visual_assets, "_decoded_frame_count", lambda _path, fallback: fallback)
    clip = visual_assets._make_source_times_safe(source, Path("cfr.mp4"))
    clip.frame_function(0.35)
    assert source.requested == [0.3]


def test_short_animated_assets_do_not_read_past_source_end() -> None:
    cases = (
        ("test_animation_short.gif", 0.8),
        ("test_animation_short.mp4", 0.97),
    )
    for filename, source_end_time in cases:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            clip = load_visual_clip(IMAGES / filename, 2.5)
            try:
                clip.get_frame(source_end_time)
            finally:
                clip.close()

        end_of_clip_warnings = [
            warning
            for warning in caught
            if isinstance(warning.message, UserWarning)
            and "0 bytes read" in str(warning.message)
        ]
        assert end_of_clip_warnings == []


def test_short_gif_preserves_all_four_source_frames() -> None:
    source = VideoFileClip(str(IMAGES / "test_animation_short.gif"), audio=False)
    clip = load_visual_clip(IMAGES / "test_animation_short.gif", 2.5)
    try:
        expected_frames = [
            source.get_frame(frame_number / source.fps)
            for frame_number in range(4)
        ]
        rendered_frames = [
            clip.get_frame(frame_number / source.fps)
            for frame_number in range(4)
        ]
        assert all(
            np.array_equal(expected, rendered)
            for expected, rendered in zip(expected_frames, rendered_frames)
        )
        assert not np.array_equal(rendered_frames[-1], rendered_frames[0])
    finally:
        clip.close()
        source.close()


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
        script = _scene_script(f"assets/backgrounds/{path.name}")
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
        script = _scene_script(f"assets/images/{path.name}", element=True)
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


def test_two_frame_gif_scene_element_preserves_scaling_and_position() -> None:
    script = _scene_script("assets/images/slay_satisfaction.gif", element=True)
    clip = build_static_scene_clip(
        script,
        script["scenes"][0],
        {"duration_sec": 1.2},
        ASSETS,
    )
    try:
        element_layer = clip.clips[1]
        assert element_layer.h == round(0.32 * 1920)
        assert element_layer.pos(0) == (
            round(540 - element_layer.w / 2),
            round(1750 - element_layer.h),
        )
        assert not np.array_equal(
            element_layer.get_frame(0.1),
            element_layer.get_frame(0.31),
        )
    finally:
        clip.close()


def test_keyframe_driven_animated_elements_keep_transformations() -> None:
    script = _script()
    script["asset_registry"]["test_visual"] = {
        "path": "assets/images/test_animation_short.mp4",
        "generate": None,
    }
    scene = script["scenes"][2]
    element = next(item for item in scene["elements"] if item["id"] == "main_character")
    element["asset"] = "test_visual"
    manifest = json.loads(
        (ROOT / "testing/fixtures/manifests/example_script.json").read_text(
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
        script = _scene_script(f"assets/images/{path.name}", element=True)
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
