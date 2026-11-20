#!/usr/bin/env python3
"""Render a local rotation demonstration using existing test assets and audio."""

from __future__ import annotations

from pathlib import Path

from moviepy import AudioFileClip, concatenate_videoclips

from creatortainment.render.moviepy_scene import build_static_scene_clip


ROOT = Path(__file__).resolve().parents[2]
ASSETS = ROOT / "testing" / "assets"
NARRATION = ROOT / "testing/assets/audio/narration/test_narration.mp3"
OUTPUT = ROOT / "testing/output/rotation_demo.mp4"
RESOLUTION = (1080, 1920)
SCENE_DURATION = 1.5


def demo_script() -> dict:
    scenes = []
    for index, rotation in enumerate((-30, 0, 30, 90), start=1):
        scenes.append(
            {
                "id": f"rotation_{rotation}",
                "bg": "background",
                "narration_text": f"Rotation {rotation} degrees",
                "duration_sec": SCENE_DURATION,
                "elements": [
                    {
                        "id": "mouse",
                        "asset": "mouse",
                        "anchor": "center",
                        "rotation": rotation,
                        "keyframes": [
                            {
                                "pos": [540, 960],
                                "target_height_frac": 0.45,
                            }
                        ],
                    }
                ],
            }
        )
    return {
        "project": {"resolution": list(RESOLUTION)},
        "asset_registry": {
            "background": {
                "path": "assets/backgrounds/default_studio.jpg",
                "generate": None,
            },
            "mouse": {
                "path": "assets/sprites/mrmouse_relaxed.png",
                "generate": None,
            },
        },
        "scenes": scenes,
    }


def main() -> None:
    script = demo_script()
    clips = [
        build_static_scene_clip(script, scene, {"duration_sec": SCENE_DURATION}, ASSETS)
        for scene in script["scenes"]
    ]
    video = concatenate_videoclips(clips, method="compose")
    narration = AudioFileClip(str(NARRATION)).subclipped(0, video.duration)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    final = video.with_audio(narration)
    try:
        final.write_videofile(
            str(OUTPUT),
            fps=30,
            codec="libx264",
            audio_codec="aac",
            logger="bar",
        )
    finally:
        final.close()
        narration.close()
        video.close()
        for clip in clips:
            clip.close()
    print(f"Rendered {OUTPUT}")


if __name__ == "__main__":
    main()
