from __future__ import annotations

import copy
from pathlib import Path

import numpy as np
from moviepy import AudioClip, ColorClip

from creatortainment.render.moviepy_scene import (
    attach_scene_narration,
    build_animated_caption_clip,
    build_full_video_clip,
    caption_text_for_scene,
)


ROOT = Path(__file__).parents[2]
ASSETS = ROOT / "testing/assets"


def _script() -> dict:
    return {
        "project": {
            "title": "Multi voice render test",
            "resolution": [320, 240],
            "fps": 10,
            "voice_id": "voice-default",
            "caption_style": {
                "font_size": 24,
                "stroke_width": 1,
                "words_per_chunk": 3,
                "highlight_color": "#FFD700",
            },
        },
        "asset_registry": {
            "background": {
                "path": "assets/backgrounds/white_portrait.jpg",
                "generate": None,
            }
        },
        "scenes": [
            {
                "id": "scene-1",
                "bg": "background",
                "narration_segments": [
                    {"id": "a", "text": "Hello there.", "voice_id": "voice-a"},
                    {"id": "b", "text": "Welcome back.", "voice_id": "voice-b"},
                ],
                "pause_before_sec": 0,
                "transition_in": None,
                "elements": [],
            }
        ],
    }


def _manifest(tmp_path: Path) -> dict:
    def write_audio(name: str, value: float) -> Path:
        path = tmp_path / f"{name}.wav"
        def frame(t):
            times = np.asarray(t)
            if times.ndim == 0:
                return np.array([value, value])
            return np.column_stack(
                (np.full(times.shape, value), np.full(times.shape, value))
            )
        clip = AudioClip(
            frame,
            duration=1.0,
            fps=44100,
        )
        try:
            clip.write_audiofile(str(path), fps=44100, codec="pcm_s16le", logger=None)
        finally:
            clip.close()
        return path

    first = write_audio("first", 0.2)
    second = write_audio("second", 0.8)
    return {
        "narration_segments": [
            {
                "id": "a",
                "scene_id": "scene-1",
                "voice_id": "voice-a",
                "text": "Hello there.",
                "audio_path": str(first),
                "start_time_sec": 0.0,
                "end_time_sec": 1.0,
                "word_timestamps": [
                    {"word": "Hello", "start": 0.0, "end": 0.25, "segment_id": "a"},
                    {"word": "there.", "start": 0.3, "end": 0.55, "segment_id": "a"},
                ],
            },
            {
                "id": "b",
                "scene_id": "scene-1",
                "voice_id": "voice-b",
                "text": "Welcome back.",
                "audio_path": str(second),
                "start_time_sec": 1.0,
                "end_time_sec": 2.0,
                "word_timestamps": [
                    {"word": "Welcome", "start": 1.0, "end": 1.25, "segment_id": "b"},
                    {"word": "back.", "start": 1.3, "end": 1.55, "segment_id": "b"},
                ],
            },
        ],
        "word_timestamps": [
            {
                "word": "Hello",
                "start": 0.0,
                "end": 0.25,
                "segment_id": "a",
                "scene_id": "scene-1",
                "voice_id": "voice-a",
            },
            {
                "word": "there.",
                "start": 0.3,
                "end": 0.55,
                "segment_id": "a",
                "scene_id": "scene-1",
                "voice_id": "voice-a",
            },
            {
                "word": "Welcome",
                "start": 1.0,
                "end": 1.25,
                "segment_id": "b",
                "scene_id": "scene-1",
                "voice_id": "voice-b",
            },
            {
                "word": "back.",
                "start": 1.3,
                "end": 1.55,
                "segment_id": "b",
                "scene_id": "scene-1",
                "voice_id": "voice-b",
            },
        ],
        "scenes": [
            {
                "id": "scene-1",
                "word_offset": 0,
                "word_count": 4,
                "start_time_sec": 0.0,
                "end_time_sec": 2.0,
                "duration_sec": 2.0,
            }
        ],
    }


def test_segment_only_scene_text_and_captions_use_flattened_timeline(tmp_path: Path) -> None:
    script = _script()
    manifest = _manifest(tmp_path)
    scene = script["scenes"][0]
    scene_manifest = manifest["scenes"][0]

    assert caption_text_for_scene(scene) == "Hello there. Welcome back."
    caption = build_animated_caption_clip(
        script,
        scene,
        scene_manifest,
        manifest,
        (320, 240),
        2.0,
    )
    try:
        assert caption.get_frame(0.01).shape[0] > 1
        assert caption.get_frame(1.1).shape[0] > 1
    finally:
        caption.close()


def test_sequential_segment_audio_is_placed_at_manifest_times(tmp_path: Path) -> None:
    script = _script()
    manifest = _manifest(tmp_path)
    scene_clip = ColorClip((320, 240), color=(0, 0, 0), duration=2.0)

    attached = attach_scene_narration(
        scene_clip,
        manifest["scenes"][0],
        manifest,
        tmp_path,
    )
    try:
        assert attached.audio is not None
        assert attached.audio.duration == 2.0
        assert float(attached.audio.get_frame(0.2)[0]) < 0.5
        assert float(attached.audio.get_frame(1.4)[0]) > 0.5
    finally:
        attached.close()


def test_full_multi_voice_scene_builds_without_global_narration_audio(tmp_path: Path) -> None:
    script = _script()
    manifest = _manifest(tmp_path)
    clip = build_full_video_clip(script, manifest, ASSETS, tmp_path)
    try:
        assert clip.duration == 2.0
        assert clip.audio is not None
    finally:
        clip.close()


def test_multiple_scenes_with_multiple_voices_build_sequentially(tmp_path: Path) -> None:
    script = _script()
    manifest = _manifest(tmp_path)
    second_scene = copy.deepcopy(script["scenes"][0])
    second_scene["id"] = "scene-2"
    second_scene["narration_segments"][0]["id"] = "c"
    second_scene["narration_segments"][1]["id"] = "d"
    script["scenes"].append(second_scene)

    second_records = copy.deepcopy(manifest["narration_segments"])
    for record, segment_id in zip(second_records, ("c", "d")):
        record["id"] = segment_id
        record["scene_id"] = "scene-2"
        record["start_time_sec"] += 2.0
        record["end_time_sec"] += 2.0
        for timestamp in record["word_timestamps"]:
            timestamp["segment_id"] = segment_id
    manifest["narration_segments"].extend(second_records)
    second_words = copy.deepcopy(manifest["word_timestamps"])
    for timestamp in second_words:
        timestamp["scene_id"] = "scene-2"
        timestamp["start"] += 2.0
        timestamp["end"] += 2.0
        timestamp["segment_id"] = "c" if timestamp["segment_id"] == "a" else "d"
    manifest["word_timestamps"].extend(second_words)
    manifest["scenes"] = [
        manifest["scenes"][0],
        {
            "id": "scene-2",
            "word_offset": 4,
            "word_count": 4,
            "start_time_sec": 2.0,
            "end_time_sec": 4.0,
            "duration_sec": 2.0,
        },
    ]

    clip = build_full_video_clip(script, manifest, ASSETS, tmp_path)
    try:
        assert clip.duration == 4.0
        assert clip.audio is not None
    finally:
        clip.close()
