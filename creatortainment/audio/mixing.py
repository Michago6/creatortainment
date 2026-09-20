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
    asset: str | None
    stop: bool
    fade_in_sec: float


@dataclass(frozen=True)
class MusicSegment:
    """One music source stretch and its normalized gain envelope."""

    start_sec: float
    end_sec: float
    asset: str
    target_gain: float
    fade_from_gain: float
    fade_in_sec: float
    duck_to_narration_pct: float


@dataclass(frozen=True)
class MusicGainTransition:
    """A gain transition on an uninterrupted source-asset run."""

    time_sec: float
    from_duck_pct: float | None
    to_duck_pct: float | None
    duration_sec: float


@dataclass
class MusicLayer:
    """One continuously looped source with gain transitions."""

    start_sec: float
    end_sec: float
    asset: str
    transitions: list[MusicGainTransition]


def _final_video_duration(scene_offsets: list[SceneOffset]) -> float:
    if not scene_offsets:
        return 0.0
    return (
        scene_offsets[-1].final_start_sec
        + scene_offsets[-1].unit_duration_sec
    )


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
        stop = bool(music.get("stop", False))
        if not stop and not isinstance(music.get("asset"), str):
            raise ValueError("A background music change must specify an asset or stop=true.")
        events.append(
            MusicEvent(
                time_sec=event_time,
                asset=None if stop else str(music["asset"]),
                stop=stop,
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
    active_asset: str | None = None
    for index, event in enumerate(events):
        end = events[index + 1].time_sec if index + 1 < len(events) else end_sec
        if event.stop:
            if active_asset is None:
                continue
            asset = active_asset
            target_gain = 0.0
            fade_from_gain = 1.0
            active_asset = None
        else:
            asset = event.asset
            if asset is None:
                continue
            target_gain = 1.0
            fade_from_gain = 1.0 if active_asset == asset else 0.0
            if active_asset == asset:
                continue
            active_asset = asset
        scene_index = next(
            (
                offset.scene_index
                for offset in reversed(scene_offsets)
                if offset.narration_start_sec <= event.time_sec
            ),
            0,
        )
        segments.append(
            MusicSegment(
                start_sec=event.time_sec,
                end_sec=end,
                asset=asset,
                target_gain=target_gain,
                fade_from_gain=fade_from_gain,
                fade_in_sec=min(event.fade_in_sec, end - event.time_sec),
                duck_to_narration_pct=_effective_duck_pct(script, scene_index),
            )
        )
    return segments


def _scene_index_at_time(
    scene_offsets: list[SceneOffset],
    time_sec: float,
) -> int:
    return next(
        (
            offset.scene_index
            for offset in reversed(scene_offsets)
            if offset.final_start_sec <= time_sec
        ),
        0,
    )


def _build_music_layers(
    script: dict[str, Any],
    manifest: dict[str, Any],
    scene_offsets: list[SceneOffset],
) -> list[MusicLayer]:
    events = build_music_events(script, manifest, scene_offsets)
    duration = _final_video_duration(scene_offsets)
    layers: list[MusicLayer] = []
    active: MusicLayer | None = None
    for event in events:
        duck_pct = _effective_duck_pct(
            script,
            _scene_index_at_time(scene_offsets, event.time_sec),
        )
        if event.stop:
            if active is None:
                continue
            active.transitions.append(
                MusicGainTransition(
                    time_sec=event.time_sec,
                    from_duck_pct=active.transitions[-1].to_duck_pct
                    or _effective_duck_pct(
                        script,
                        _scene_index_at_time(scene_offsets, event.time_sec),
                    ),
                    to_duck_pct=None,
                    duration_sec=event.fade_in_sec,
                )
            )
            active.end_sec = min(duration, event.time_sec + event.fade_in_sec)
            active = None
            continue
        if event.asset is None:
            continue
        if active is not None and active.asset == event.asset:
            previous = active.transitions[-1].to_duck_pct
            if previous is None:
                previous = duck_pct
            active.transitions.append(
                MusicGainTransition(
                    time_sec=event.time_sec,
                    from_duck_pct=previous,
                    to_duck_pct=duck_pct,
                    duration_sec=event.fade_in_sec,
                )
            )
            continue
        if active is not None:
            active.transitions.append(
                MusicGainTransition(
                    time_sec=event.time_sec,
                    from_duck_pct=active.transitions[-1].to_duck_pct
                    or _effective_duck_pct(
                        script,
                        _scene_index_at_time(scene_offsets, event.time_sec),
                    ),
                    to_duck_pct=None,
                    duration_sec=event.fade_in_sec,
                )
            )
            active.end_sec = min(duration, event.time_sec + event.fade_in_sec)
        active = MusicLayer(
            start_sec=event.time_sec,
            end_sec=duration,
            asset=event.asset,
            transitions=[
                MusicGainTransition(
                    time_sec=event.time_sec,
                    from_duck_pct=None,
                    to_duck_pct=duck_pct,
                    duration_sec=event.fade_in_sec,
                )
            ],
        )
        layers.append(active)
    return layers


def _effective_duck_pct(script: dict[str, Any], scene_index: int) -> float:
    project_pct = float(script.get("project", {}).get("duck_to_narration_pct", 0.3))
    scene = script.get("scenes", [])[scene_index]
    override = scene.get("duck_to_narration_pct")
    return project_pct if override is None else float(override)


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
    duck_gain: float | Callable[[np.ndarray], float | np.ndarray],
    narration_intervals: list[tuple[float, float]],
) -> float | np.ndarray:
    """Return the continuously ducked gain for an active music segment."""
    times = np.asarray(time_sec, dtype=float)
    elapsed = times - segment.start_sec
    if segment.fade_in_sec > 0.0:
        progress = np.minimum(1.0, np.maximum(0.0, elapsed / segment.fade_in_sec))
        baseline = segment.fade_from_gain + (
            segment.target_gain - segment.fade_from_gain
        ) * progress
    else:
        baseline = np.full_like(times, segment.target_gain)
    in_segment = (times >= segment.start_sec) & (times < segment.end_sec)
    resolved_duck_gain = (
        duck_gain(times) if callable(duck_gain) else duck_gain
    )
    gains = np.where(in_segment, baseline * resolved_duck_gain, 0.0)
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
    layers = _build_music_layers(script, manifest, scene_offsets)
    if not layers:
        return _silence(duration)
    cache = loudness_cache or LoudnessCache()
    clips = []
    registry = script["asset_registry"]
    for layer in layers:
        path = _asset_path(registry, layer.asset, assets_root)
        music_loudness = cache.measure(path)
        duck_gains = {
            transition.to_duck_pct: compute_duck_gain(
                narration_loudness,
                music_loudness,
                transition.to_duck_pct,
            )
            for transition in layer.transitions
            if transition.to_duck_pct is not None
        }
        resolved_transitions: list[tuple[float, float, float, float]] = []

        def gain_at_absolute_time(time_sec: float) -> float:
            value = 0.0
            for start, from_gain, to_gain, fade_duration in resolved_transitions:
                if time_sec < start:
                    break
                if fade_duration <= 0.0 or time_sec >= start + fade_duration:
                    value = to_gain
                else:
                    progress = (time_sec - start) / fade_duration
                    value = from_gain + (to_gain - from_gain) * progress
            return value

        for transition in layer.transitions:
            target = (
                0.0
                if transition.to_duck_pct is None
                else duck_gains[transition.to_duck_pct]
            )
            from_gain = (
                0.0
                if transition.from_duck_pct is None
                else duck_gains[transition.from_duck_pct]
            )
            resolved_transitions.append(
                (
                    transition.time_sec,
                    from_gain,
                    target,
                    transition.duration_sec,
                )
            )
        layer_duration = layer.end_sec - layer.start_sec
        source = AudioFileClip(str(path))
        looped = source.with_effects([AudioLoop(duration=layer_duration)])

        def gain_frame(
            get_frame,
            local_time,
            layer=layer,
            resolved_transitions=resolved_transitions,
        ):
            local_times = np.asarray(local_time, dtype=float)
            absolute_times = layer.start_sec + local_times
            gains = np.zeros_like(absolute_times)
            for start, from_gain, target, fade_duration in resolved_transitions:
                after = absolute_times >= start
                if fade_duration <= 0.0:
                    gains = np.where(after, target, gains)
                    continue
                progress = np.clip(
                    (absolute_times - start) / fade_duration,
                    0.0,
                    1.0,
                )
                transition_gain = from_gain + (target - from_gain) * progress
                gains = np.where(after, transition_gain, gains)
            gains = np.where(
                (absolute_times >= layer.start_sec)
                & (absolute_times < layer.end_sec),
                gains,
                0.0,
            )
            frames = get_frame(local_time)
            if gains.ndim == 0:
                return frames * float(gains)
            return frames * gains.reshape((-1, 1))

        clips.append(
            looped.transform(gain_frame, keep_duration=True)
            .with_start(layer.start_sec)
        )
    return CompositeAudioClip(clips).with_duration(duration)
