"""Background music planning and MoviePy track assembly."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from moviepy import AudioClip, AudioFileClip, CompositeAudioClip
from moviepy.audio.fx import AudioLoop

from ..render.mock import _asset_path
from ..render.timeline import (
    SceneOffset,
    build_scene_final_offsets,
    resolve_cue_to_final_video_time,
)
from .loudness import LoudnessCache, compute_duck_gain


@dataclass(frozen=True)
class MusicEvent:
    """A resolved background-music change event."""

    time_sec: float
    asset: str
    volume: float
    fade_in_sec: float


@dataclass(frozen=True)
class MusicSegment:
    """One music source stretch and its baseline gain envelope."""

    start_sec: float
    end_sec: float
    asset: str
    volume: float
    fade_from_volume: float
    fade_in_sec: float


def _final_video_duration(scene_offsets: list[SceneOffset]) -> float:
    if not scene_offsets:
        return 0.0
    return scene_offsets[-1].narration_end_sec


def build_music_events(
    script: dict[str, Any],
    manifest: dict[str, Any],
    scene_offsets: list[SceneOffset],
) -> list[MusicEvent]:
    """Resolve non-null scene music changes through the shared cue mapper."""
    events: list[MusicEvent] = []
    for scene in script.get("scenes", []):
        music = scene.get("bg_music")
        if music is None:
            continue
        event_time = resolve_cue_to_final_video_time(
            scene,
            int(music["trigger_word_index"]),
            manifest,
            scene_offsets,
        )
        events.append(
            MusicEvent(
                time_sec=event_time,
                asset=str(music["asset"]),
                volume=float(music.get("volume", 1.0)),
                fade_in_sec=max(0.0, float(music.get("fade_in_sec", 0.0))),
            )
        )
    return sorted(events, key=lambda event: event.time_sec)


def build_music_segments(
    script: dict[str, Any],
    manifest: dict[str, Any],
    scene_offsets: list[SceneOffset],
) -> list[MusicSegment]:
    """Convert music change events into source stretches through video end."""
    events = build_music_events(script, manifest, scene_offsets)
    if not events:
        return []
    end_sec = _final_video_duration(scene_offsets)
    segments: list[MusicSegment] = []
    previous_volume = 0.0
    for index, event in enumerate(events):
        end = events[index + 1].time_sec if index + 1 < len(events) else end_sec
        if end <= event.time_sec:
            continue
        fade_from = previous_volume if segments and segments[-1].asset == event.asset else 0.0
        segments.append(
            MusicSegment(
                start_sec=event.time_sec,
                end_sec=end,
                asset=event.asset,
                volume=max(0.0, event.volume),
                fade_from_volume=fade_from,
                fade_in_sec=min(event.fade_in_sec, end - event.time_sec),
            )
        )
        previous_volume = max(0.0, event.volume)
    return segments


def _narration_intervals(scene_offsets: list[SceneOffset]) -> list[tuple[float, float]]:
    return [
        (offset.narration_start_sec, offset.narration_end_sec)
        for offset in scene_offsets
    ]


def _is_narration_time(time_sec: float, intervals: list[tuple[float, float]]) -> bool:
    return any(start <= time_sec < end for start, end in intervals)


def music_gain_at_time(
    segment: MusicSegment,
    time_sec: float | np.ndarray,
    duck_gain: float,
    narration_intervals: list[tuple[float, float]],
) -> float | np.ndarray:
    """Return the continuously ducked gain for an active music segment."""
    times = np.asarray(time_sec, dtype=float)
    elapsed = times - segment.start_sec
    if segment.fade_in_sec > 0.0:
        progress = np.minimum(1.0, np.maximum(0.0, elapsed / segment.fade_in_sec))
        baseline = segment.fade_from_volume + (
            segment.volume - segment.fade_from_volume
        ) * progress
    else:
        baseline = np.full_like(times, segment.volume)
    in_segment = (times >= segment.start_sec) & (times < segment.end_sec)
    gains = np.where(in_segment, baseline * duck_gain, 0.0)
    return float(gains) if gains.ndim == 0 else gains


@dataclass(frozen=True)
class SfxCue:
    """A resolved one-shot sound-effect cue."""

    time_sec: float
    asset: str
    volume: float


def build_sfx_cues(
    script: dict[str, Any],
    manifest: dict[str, Any],
    scene_offsets: list[SceneOffset],
) -> list[SfxCue]:
    """Resolve every scene SFX cue through the shared final-time mapper."""
    cues: list[SfxCue] = []
    for scene in script.get("scenes", []):
        for sfx in scene.get("sfx", []):
            cues.append(
                SfxCue(
                    time_sec=resolve_cue_to_final_video_time(
                        scene,
                        int(sfx["trigger_word_index"]),
                        manifest,
                        scene_offsets,
                    ),
                    asset=str(sfx["asset"]),
                    volume=max(0.0, float(sfx.get("volume", 1.0))),
                )
            )
    return sorted(cues, key=lambda cue: cue.time_sec)


def build_sfx_track(
    script: dict[str, Any],
    manifest: dict[str, Any],
    assets_root: Path,
    *,
    scene_offsets: list[SceneOffset] | None = None,
):
    """Build one-shot SFX layers clipped to the final video duration."""
    offsets = scene_offsets or build_scene_final_offsets(script, manifest)
    duration = _final_video_duration(offsets)
    registry = script["asset_registry"]
    clips = []
    for cue in build_sfx_cues(script, manifest, offsets):
        if cue.time_sec >= duration:
            continue
        path = _asset_path(registry, cue.asset, assets_root)
        source = AudioFileClip(str(path))
        clip_duration = min(float(source.duration), duration - cue.time_sec)
        if clip_duration <= 0.0:
            source.close()
            continue
        clips.append(
            source.subclipped(0, clip_duration)
            .with_volume_scaled(cue.volume)
            .with_start(cue.time_sec)
        )
    if not clips:
        return _silence(duration)
    return CompositeAudioClip(clips).with_duration(duration)


def build_final_audio_mix(
    narration_audio,
    script: dict[str, Any],
    manifest: dict[str, Any],
    assets_root: Path,
    project_dir: Path,
    *,
    loudness_cache: LoudnessCache | None = None,
):
    """Combine pause-aligned narration, music, and SFX into one final track."""
    narration_path = Path(manifest["narration_audio_path"])
    if not narration_path.is_absolute():
        narration_path = project_dir / narration_path
    cache = loudness_cache or LoudnessCache()
    narration_loudness = cache.measure(narration_path)
    scene_offsets = build_scene_final_offsets(script, manifest)
    music = build_background_music_track(
        script,
        manifest,
        assets_root,
        project_dir,
        narration_loudness,
        loudness_cache=cache,
    )
    sfx = build_sfx_track(
        script,
        manifest,
        assets_root,
        scene_offsets=scene_offsets,
    )
    return CompositeAudioClip([narration_audio, music, sfx]).with_duration(
        _final_video_duration(scene_offsets)
    )


def _silence(duration: float) -> AudioClip:
    return AudioClip(
        frame_function=lambda t: np.zeros(2, dtype=float),
        duration=duration,
        fps=44100,
    )


def build_background_music_track(
    script: dict[str, Any],
    manifest: dict[str, Any],
    assets_root: Path,
    project_dir: Path,
    narration_loudness: float,
    *,
    loudness_cache: LoudnessCache | None = None,
):
    """Build one continuous, looped and ducked background music track."""
    scene_offsets = build_scene_final_offsets(script, manifest)
    duration = _final_video_duration(scene_offsets)
    segments = build_music_segments(script, manifest, scene_offsets)
    if not segments:
        return _silence(duration)
    cache = loudness_cache or LoudnessCache()
    duck_pct = float(script.get("project", {}).get("duck_to_narration_pct", 0.3))
    intervals = _narration_intervals(scene_offsets)
    clips = []
    registry = script["asset_registry"]
    for segment in segments:
        path = _asset_path(registry, segment.asset, assets_root)
        music_loudness = cache.measure(path)
        duck_gain = compute_duck_gain(narration_loudness, music_loudness, duck_pct)
        segment_duration = segment.end_sec - segment.start_sec
        source = AudioFileClip(str(path))
        looped = source.with_effects([AudioLoop(duration=segment_duration)])

        def gain_frame(get_frame, local_time, segment=segment, duck_gain=duck_gain):
            local_times = np.asarray(local_time, dtype=float)
            absolute_times = segment.start_sec + local_times
            elapsed = absolute_times - segment.start_sec
            if segment.fade_in_sec > 0.0:
                progress = np.minimum(1.0, elapsed / segment.fade_in_sec)
                baseline = segment.fade_from_volume + (
                    segment.volume - segment.fade_from_volume
                ) * progress
            else:
                baseline = np.full_like(absolute_times, segment.volume)
            gains = baseline * duck_gain
            frames = get_frame(local_time)
            if gains.ndim == 0:
                return frames * float(gains)
            return frames * gains.reshape((-1, 1))

        clips.append(
            looped.transform(gain_frame, keep_duration=True)
            .with_start(segment.start_sec)
        )
    return CompositeAudioClip(clips).with_duration(duration)
