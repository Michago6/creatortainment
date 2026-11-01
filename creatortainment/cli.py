"""Command-line interface for Creatortainment."""

from __future__ import annotations

import argparse
import copy
import json
import os
import shutil
import subprocess
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .audio.alignment import align_scenes
from .audio.elevenlabs_client import ElevenLabsNarrationClient
from .audio.manifest import (
    DEFAULT_TTS_MODEL,
    DEFAULT_TTS_SPEED,
    AUDIO_DURATION_TOLERANCE_SEC,
    audio_duration_sec,
    cached_words_match,
    narration_text_and_pauses,
    narration_hash,
    narration_hash_for_text,
    read_manifest,
    refresh_cached_manifest_scenes,
    write_manifest,
)
from .audio.manifest import build_segment_manifest
from .audio.segment_cache import (
    cached_segment_paths,
    find_cached_segment,
    write_cached_segment,
)
from .asset_generation import generate_assets
from . import config
from .project_identity import (
    new_state,
    project_state_path,
    read_project_state,
    slugify,
    variant_manifest_path,
    write_project_state,
)
from .render.moviepy_scene import build_full_video_clip
from .render.mock import render_storyboard
from .schema.validate import (
    ScriptValidationError,
    asset_generation_plans,
    load_script,
    validate_script,
)
from .provider_validation import (
    validate_elevenlabs_capabilities,
    validate_elevenlabs_values,
    validate_fal_models,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
ASSETS_ROOT = REPO_ROOT / "scriptwriting" / "assets"
PROJECTS_ROOT = REPO_ROOT / "projects"


def _stdin_is_interactive() -> bool:
    """Return whether prompting on stdin is safe."""
    try:
        return sys.stdin is not None and sys.stdin.isatty()
    except (OSError, ValueError):
        return False


def open_with_default_application(path: Path) -> bool:
    """Launch a file with the platform's default application without waiting."""
    try:
        if sys.platform == "win32":
            os.startfile(str(path))
            return True
        command = ["open", str(path)] if sys.platform == "darwin" else None
        if command is None:
            opener = shutil.which("xdg-open")
            if opener is None:
                return False
            command = [opener, str(path)]
        subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        return True
    except (OSError, ValueError):
        return False


def _prompt_to_open_output(path: Path) -> None:
    """Optionally open a successful output without affecting command success."""
    if not _stdin_is_interactive():
        return
    try:
        answer = input("Open with default application? [Y/n] ").strip().lower()
    except (EOFError, OSError):
        return
    if answer in {"n", "no"}:
        return
    if not open_with_default_application(path):
        print(
            f"Warning: could not open output with the default application: {path}",
            file=sys.stderr,
        )


def output_timestamp(now: datetime | None = None) -> str:
    """Return the shared timestamp format used for generated visual outputs."""
    return (now or datetime.now()).strftime("%Y%m%d_%H%M%S")


def output_filename(
    kind: str,
    *,
    timestamp: str,
    preview: bool = False,
) -> str:
    """Build a timestamped render or storyboard filename."""
    if kind == "render":
        suffix = "_preview" if preview else ""
        return f"render_{timestamp}{suffix}.mp4"
    if kind == "storyboard":
        return f"storyboard_{timestamp}.png"
    raise ValueError(f"Unknown output kind: {kind!r}")


def non_overwriting_path(
    path: Path,
    *,
    timestamp: str,
) -> Path:
    """Return a path that does not overwrite an existing output."""
    if not path.exists():
        return path
    candidate = path.with_name(
        f"{path.stem}_{timestamp}{path.suffix}"
    )
    collision_time = datetime.strptime(timestamp, "%Y%m%d_%H%M%S")
    while candidate.exists():
        collision_time += timedelta(seconds=1)
        candidate = path.with_name(
            f"{path.stem}_{output_timestamp(collision_time)}{path.suffix}"
        )
    return candidate


def scale_script_for_preview(script: dict) -> dict:
    """Scale canvas coordinates and caption sizes before preview rendering."""
    scaled = copy.deepcopy(script)
    width, height = (int(value) for value in script["project"]["resolution"])
    preview_width = max(1, round(width * 0.25))
    preview_height = max(1, round(height * 0.25))
    project = scaled["project"]
    _set_script_value(project, "resolution", [preview_width, preview_height])

    project_style = project.get("caption_style")
    if project_style is not None and _has_script_value(project_style, "font_size"):
        _set_script_value(
            project_style,
            "font_size",
            max(1, round(float(project_style["font_size"]) * 0.25)),
        )
    for scene in scaled.get("scenes", []):
        scene_style = scene.get("caption_style")
        if scene_style is not None and _has_script_value(scene_style, "font_size"):
            _set_script_value(
                scene_style,
                "font_size",
                max(1, round(float(scene_style["font_size"]) * 0.25)),
            )
        for element in scene.get("elements", []):
            for keyframe in element.get("keyframes", []):
                position = keyframe.get("pos")
                if isinstance(position, (list, tuple)) and len(position) == 2:
                    _set_script_value(
                        keyframe,
                        "pos",
                        [
                            float(position[0]) * 0.25,
                            float(position[1]) * 0.25,
                        ],
                    )
    return scaled


def _has_script_value(value: object, key: str) -> bool:
    """Check a script field on either a mapping-compatible model or a dict."""
    if isinstance(value, dict):
        return key in value
    return key in value


def _set_script_value(value: object, key: str, new_value: object) -> None:
    """Set a script field on either a mapping-compatible model or a dict."""
    if isinstance(value, dict):
        value[key] = new_value
    else:
        value[key] = new_value


def prepare_render_clip(clip, resolution: tuple[int, int], preview: bool):
    """Validate the explicitly selected preview or full-resolution path."""
    encoded_clip = clip
    expected_size = (
        (round(resolution[0] * 0.25), round(resolution[1] * 0.25))
        if preview
        else resolution
    )
    if tuple(encoded_clip.size) != tuple(expected_size):
        raise RuntimeError(
            f"Render output size {encoded_clip.size} does not match expected "
            f"{expected_size}."
        )
    return encoded_clip


def project_slug(title: str) -> str:
    return slugify(title)


def _group_missing_generation_models(plans) -> str | None:
    counts = Counter(
        plan.generation_method
        for plan in plans
        if plan.effective_model is None
    )
    if not counts:
        return None
    lines = ["Asset generation:"]
    lines.extend(
        f"- No model configured for {method} ({count} assets)"
        for method, count in counts.items()
    )
    return "\n".join(lines)


def _print_validation_error(error: str) -> None:
    if error.startswith("Asset generation:\n"):
        print(error, file=sys.stderr)
    else:
        print(f"- {error}", file=sys.stderr)


def _format_json_path(location: tuple[Any, ...]) -> str:
    path = ""
    for part in location:
        if isinstance(part, int):
            path += f"[{part}]"
        else:
            path += f".{part}" if path else str(part)
    return path or "<script>"


def _format_actual_value(value: object) -> str:
    if isinstance(value, str):
        return f"a string ({value!r})"
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "a boolean"
    if isinstance(value, dict):
        return "an object"
    if isinstance(value, list):
        return "an array"
    return type(value).__name__


def _format_pydantic_error(error: dict[str, Any]) -> str:
    error_type = error.get("type")
    actual = _format_actual_value(error.get("input"))
    if error_type in {"dict_type", "model_type"}:
        if tuple(error.get("loc", ()))[:1] == ("asset_registry",):
            return f"Expected an asset object, but got {actual}."
        return f"Expected an object, but got {actual}."
    if error_type == "string_type":
        return f"Expected a string, but got {actual}."
    if error_type in {"int_type", "int_parsing"}:
        return f"Expected an integer, but got {actual}."
    if error_type in {"float_type", "float_parsing"}:
        return f"Expected a number, but got {actual}."
    if error_type == "bool_type":
        return f"Expected a boolean, but got {actual}."
    if error_type == "list_type":
        return f"Expected an array, but got {actual}."
    if error_type == "missing":
        return "This required value is missing."
    if error_type == "literal_error":
        expected = error.get("ctx", {}).get("expected")
        return f"Expected {expected or 'one of the allowed values'}; got {error.get('input')!r}."
    return error.get("msg", "Value does not satisfy the schema.")


def format_validation_errors(errors: list[dict[str, Any]]) -> list[str]:
    """Format structured Pydantic errors as concise, path-aware CLI lines."""
    grouped: dict[tuple[str, str], list[str]] = {}
    legacy_asset_paths: list[str] = []
    for error in errors:
        path = _format_json_path(tuple(error.get("loc", ())))
        message = _format_pydantic_error(error)
        key = (error.get("type", ""), message)
        grouped.setdefault(key, []).append(path)
        location = tuple(error.get("loc", ()))
        if (
            len(location) >= 2
            and location[0] == "asset_registry"
            and isinstance(error.get("input"), str)
        ):
            legacy_asset_paths.append(path)

    lines: list[str] = []
    for (_, message), paths in grouped.items():
        lines.append(f"✗ {', '.join(paths)}\n  {message}")
    if len(legacy_asset_paths) >= 2:
        lines.append(
            "Hint: asset_registry entries must use the current object format.\n"
            "This script appears to use the legacy string format."
        )
    return lines


def validate_command(script_path: Path, asset_gen_info: bool = False) -> int:
    try:
        script = load_script(script_path)
    except ScriptValidationError as exc:
        print(f"Invalid: {script_path}", file=sys.stderr)
        for error in format_validation_errors(exc.errors):
            print(error, file=sys.stderr)
        return 1
    result = validate_script(script, ASSETS_ROOT)
    plans = asset_generation_plans(script)
    effective_models = {
        plan.effective_model for plan in plans if plan.effective_model is not None
    }
    if not result.errors:
        normalize_segments = getattr(script, "normalized_narration_segments", None)
        if callable(normalize_segments):
            narration_texts = [segment.text for segment in normalize_segments()]
        else:
            narration_texts = []
            for scene in script.get("scenes", []):
                segments = scene.get("narration_segments")
                if isinstance(segments, list):
                    narration_texts.extend(
                        item["text"]
                        for item in segments
                        if isinstance(item, dict) and isinstance(item.get("text"), str)
                    )
                elif isinstance(scene.get("narration_text"), str):
                    narration_texts.append(scene["narration_text"])
        result.errors.extend(
            validate_elevenlabs_capabilities(
                script["project"]["tts_model"],
                script["project"].get("speed", DEFAULT_TTS_SPEED),
                narration_texts,
            )
        )
        segment_voice_ids = (
            {
                segment.voice_id
                for segment in normalize_segments()
                if segment.voice_id != script["project"]["voice_id"]
            }
            if callable(normalize_segments)
            else set()
        )
        result.errors.extend(
            error
            for error in validate_elevenlabs_values(
                script["project"]["tts_model"],
                script["project"]["voice_id"],
                segment_voice_ids,
            )
        )
        missing_models_error = _group_missing_generation_models(plans)
        if missing_models_error:
            result.errors.append(missing_models_error)
        result.errors.extend(
            validate_fal_models(effective_models)
        )
    if asset_gen_info:
        print("Asset generation plan:")
        for plan in plans:
            model = plan.effective_model or "<unresolved>"
            source = f", source_asset={plan.source_asset}" if plan.source_asset else ""
            print(
                f"- {plan.asset_key}: method={plan.generation_method}, "
                f"model={model}{source}"
            )
    if result.valid:
        print(f"Valid: {script_path}")
        return 0
    print(f"Invalid: {script_path}", file=sys.stderr)
    for error in result.errors:
        _print_validation_error(error)
    return 1


def generate_assets_command(script_path: Path, force: bool) -> int:
    script = load_script(script_path)
    result = validate_script(script, ASSETS_ROOT)
    if not result.valid:
        print("Cannot generate assets for an invalid script:", file=sys.stderr)
        for error in result.errors:
            _print_validation_error(error)
        return 1
    try:
        generated, skipped, failed = generate_assets(
            script,
            ASSETS_ROOT,
            force=force,
        )
    except Exception as exc:
        print(f"Asset generation failed: {exc}", file=sys.stderr)
        return 1
    for asset_key in generated:
        print(f"Generated: {asset_key}")
    for asset_key in skipped:
        print(f"Skipped (already exists): {asset_key}")
    for error in failed:
        print(f"Failed: {error}", file=sys.stderr)
    return 1 if failed else 0


def render_command(script_path: Path, output: Path | None, preview: bool) -> int:
    script = load_script(script_path)
    result = validate_script(script, ASSETS_ROOT)
    if not result.valid:
        print("Cannot render an invalid script:", file=sys.stderr)
        for error in result.errors:
            print(f"- {error}", file=sys.stderr)
        return 1

    project_dir = PROJECTS_ROOT / project_slug(script["project"]["title"])
    project_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(script_path, project_dir / "script.json")
    timestamp = output_timestamp()
    destination = output or (
        project_dir
        / "output"
        / output_filename("render", timestamp=timestamp, preview=preview)
    )
    if not destination.is_absolute():
        destination = project_dir / destination
    destination = non_overwriting_path(destination, timestamp=timestamp)
    manifest_path = variant_manifest_path(project_dir, script_path)
    if not manifest_path.is_file():
        manifest_path = project_dir / "build_manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(
            f"No build manifest found for {script_path}. "
            "Run align for this script before rendering."
        )
    manifest = read_manifest(manifest_path)
    try:
        print("Checking cached narration scene boundaries...", flush=True)
        if refresh_cached_manifest_scenes(
            script,
            manifest,
            project_dir,
            boundary_status=lambda message: print(message, flush=True),
        ):
            write_manifest(manifest_path, manifest)
            if manifest_path != project_dir / "build_manifest.json":
                write_manifest(project_dir / "build_manifest.json", manifest)
    except (FileNotFoundError, ValueError) as exc:
        raise RuntimeError(str(exc)) from exc
    render_script = scale_script_for_preview(script) if preview else script
    clip = build_full_video_clip(
        render_script,
        manifest,
        ASSETS_ROOT,
        project_dir,
        show_scene_numbers=preview,
    )
    encoded_clip = prepare_render_clip(
        clip,
        tuple(script["project"]["resolution"]),
        preview,
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    fps = int(script["project"]["fps"])
    encoded_clip.write_videofile(
        str(destination),
        fps=min(fps, 15) if preview else fps,
        codec="libx264",
        audio_codec="aac",
        preset="ultrafast" if preview else "medium",
        logger="bar",
    )
    if encoded_clip is not clip:
        encoded_clip.close()
    clip.close()
    print(f"Project: {project_dir}")
    print(f"Video render: {destination}")
    if preview:
        print("Preview mode: quarter resolution, reduced frame rate, and fast encoding.")
    _prompt_to_open_output(destination)
    return 0


def storyboard_command(script_path: Path, output: Path | None) -> int:
    script = load_script(script_path)
    result = validate_script(script, ASSETS_ROOT)
    if not result.valid:
        print("Cannot render a storyboard for an invalid script:", file=sys.stderr)
        for error in result.errors:
            print(f"- {error}", file=sys.stderr)
        return 1

    project_dir = PROJECTS_ROOT / project_slug(script["project"]["title"])
    project_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(script_path, project_dir / "script.json")
    timestamp = output_timestamp()
    destination = output or (
        project_dir / output_filename("storyboard", timestamp=timestamp)
    )
    if not destination.is_absolute():
        destination = project_dir / destination
    destination = non_overwriting_path(destination, timestamp=timestamp)
    destination.parent.mkdir(parents=True, exist_ok=True)
    render_storyboard(script, ASSETS_ROOT, destination)
    print(f"Project: {project_dir}")
    print(f"Storyboard: {destination}")
    _prompt_to_open_output(destination)
    return 0


def repair_cached_manifest_timing(
    script: dict,
    manifest_path: Path,
    project_dir: Path,
) -> bool:
    """Rewrite stale scene offsets from raw timestamps without calling ElevenLabs."""
    manifest = read_manifest(manifest_path)
    audio_path = Path(manifest["narration_audio_path"])
    if not audio_path.is_absolute():
        audio_path = project_dir / audio_path
    if not audio_path.is_file():
        raise FileNotFoundError(f"Narration audio file does not exist: {audio_path}")
    final_end = max(
        (float(scene["end_time_sec"]) for scene in manifest.get("scenes", [])),
        default=0.0,
    )
    audio_duration = audio_duration_sec(audio_path, final_end)
    if final_end <= audio_duration + AUDIO_DURATION_TOLERANCE_SEC:
        return False

    timestamps = manifest.get("word_timestamps")
    if not isinstance(timestamps, list):
        raise ValueError(f"Cached manifest has no usable word_timestamps: {manifest_path}")
    manifest["scenes"] = [
        scene.to_dict()
        for scene in align_scenes(
            script["scenes"],
            timestamps,
            narration_duration_sec=audio_duration,
            audio_path=audio_path,
        )
    ]
    write_manifest(manifest_path, manifest)
    return True


def find_matching_narration(
    project_dir: Path,
    expected_hash: str,
    expected_text: str | None = None,
    expected_speed: float = DEFAULT_TTS_SPEED,
) -> tuple[Path, list[dict[str, Any]]] | None:
    """Find any retained narration sidecar matching the requested hash."""
    narrations_dir = project_dir / "narrations"
    if not narrations_dir.is_dir():
        return None
    for sidecar_path in sorted(narrations_dir.glob("*.json")):
        try:
            sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        text = sidecar.get("narration_text")
        model = sidecar.get("tts_model", DEFAULT_TTS_MODEL)
        timestamps = sidecar.get("word_timestamps")
        if (
            not isinstance(text, str)
            or not isinstance(model, str)
            or not isinstance(timestamps, list)
            or narration_hash_for_text(text, model, expected_speed) != expected_hash
            or (
                expected_text is not None
                and not cached_words_match(text, timestamps)
            )
        ):
            continue
        audio_path = sidecar_path.with_suffix(".mp3")
        if audio_path.is_file():
            return audio_path, timestamps
    return None


def align_command(script_path: Path, force_audio: bool, debug: bool) -> int:
    script = load_script(script_path)
    result = validate_script(script, ASSETS_ROOT)
    if not result.valid:
        print("Cannot align an invalid script:", file=sys.stderr)
        for error in result.errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    title = script["project"]["title"]
    project_dir = PROJECTS_ROOT / project_slug(title)
    debug_log = project_dir / "debug.log" if debug else None
    if debug:
        debug_log.parent.mkdir(parents=True, exist_ok=True)
        debug_log.write_text(
            f"align start script={script_path} project={project_dir}\n",
            encoding="utf-8",
        )
    incoming_hash = narration_hash(script)
    initialized = project_state_path(project_dir).is_file()
    model = script["project"].get("tts_model", DEFAULT_TTS_MODEL)
    speed = script["project"].get("speed", DEFAULT_TTS_SPEED)
    voice_id = script["project"].get("voice_id")
    if not isinstance(voice_id, str) or not voice_id.strip():
        raise RuntimeError(
            "project.voice_id is required in the input script and must contain an ElevenLabs voice ID."
        )
    matched_audio = (
        find_matching_narration(
            project_dir,
            incoming_hash,
            narration_text_and_pauses(script["scenes"])[0],
            speed,
        )
        if initialized
        else None
    )
    if initialized and not force_audio:
        state = read_project_state(project_state_path(project_dir))
        print(f"A project named '{title}' already exists (last updated {state.get('updated_at', 'unknown')}).")
        same = matched_audio is not None
        if same:
            print("Same audio description detected. New audio won't be created.")
        else:
            print(
                "A new audio for this project will be created. The existing narration "
                "will not be overwritten — a new file will be added to this project's narrations/ folder."
            )
        if input(f"Update existing project '{title}' with this script? [y/N] ").strip().lower() not in {"y", "yes"}:
            print("Update cancelled; no files were changed.")
            return 0
        if same and matched_audio is not None:
            audio_path, timestamps = matched_audio
            manifest = {
                "narration_hash": incoming_hash,
                "narration_audio_path": str(audio_path.relative_to(project_dir)),
                "tts_model": model,
                "speed": speed,
                "word_timestamps": timestamps,
                "scenes": [
                    scene.to_dict()
                    for scene in align_scenes(script["scenes"], timestamps)
                ],
            }
            refresh_cached_manifest_scenes(
                script,
                manifest,
                project_dir,
            )
            manifest_path = variant_manifest_path(project_dir, script_path)
            write_manifest(manifest_path, manifest)
            write_manifest(project_dir / "build_manifest.json", manifest)
            state.update({"title": title, "date": script["project"].get("date"), "updated_at": datetime.now(timezone.utc).isoformat()})
            state["narration_hash"] = incoming_hash
            state["tts_model"] = model
            state["speed"] = speed
            write_project_state(project_state_path(project_dir), state)
            shutil.copy2(script_path, project_dir / "script.json")
            print("Project metadata updated; existing narration remains active.")
            return 0
    elif not initialized:
        project_dir.mkdir(parents=True, exist_ok=True)
        write_project_state(project_state_path(project_dir), new_state(script))

    project_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(script_path, project_dir / "script.json")
    api_key = config.get_elevenlabs_api_key()
    client = ElevenLabsNarrationClient(
        api_key,
        voice_id=voice_id,
        model_id=model,
        speed=speed,
        debug_log=debug_log,
    )
    normalized_segments = script.normalized_narration_segments()
    if any(scene.narration_segments is not None for scene in script.scenes):
        narrations_dir = project_dir / "narrations"
        segment_results = []
        segment_audio_paths = []
        generated = 0
        reused = 0
        for segment in normalized_segments:
            cached_segment = find_cached_segment(narrations_dir, segment, model, speed)
            if cached_segment is not None:
                segment_results.append(cached_segment)
                segment_audio_paths.append(
                    cached_segment_paths(narrations_dir, segment, model, speed)[0]
                )
                reused += 1
                continue
            result = client.synthesize_segments([segment])[0]
            audio_path, _ = write_cached_segment(narrations_dir, result, model, speed)
            segment_results.append(result)
            segment_audio_paths.append(audio_path)
            generated += 1
        manifest = build_segment_manifest(
            script,
            project_dir / "build_manifest.json",
            project_dir,
            segment_results,
            segment_audio_paths,
            model,
            speed,
        )
        write_manifest(variant_manifest_path(project_dir, script_path), manifest)
        print(
            f"Generated {generated} narration segment(s); "
            f"reused {reused} cached segment(s)."
        )
        print(f"Updated manifest: {project_dir / 'build_manifest.json'}")
        return 0

    result = client.synthesize(script["scenes"])
    now = datetime.now(timezone.utc)
    compact = now.strftime("%Y%m%dT%H%M%S%fZ")
    short_hash = incoming_hash[:12]
    narrations_dir = project_dir / "narrations"
    narrations_dir.mkdir(exist_ok=True)
    audio_path = narrations_dir / f"{short_hash}_{compact}.mp3"
    while audio_path.exists() or audio_path.with_suffix(".json").exists():
        compact = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        audio_path = narrations_dir / f"{short_hash}_{compact}.mp3"
    sidecar_path = audio_path.with_suffix(".json")
    audio_path.write_bytes(result.audio_bytes)
    timestamps = [timestamp.to_dict() for timestamp in result.word_timestamps]
    narration_duration = audio_duration_sec(
        audio_path,
        max((float(item["end"]) for item in timestamps), default=0.0),
    )
    sidecar_path.write_text(json.dumps({
        "narration_text": " ".join(scene["narration_text"].strip() for scene in script["scenes"]),
        "tts_model": model,
        "speed": speed,
        "word_timestamps": timestamps,
        "created_at": now.isoformat(),
    }, indent=2) + "\n", encoding="utf-8")
    manifest = {
        "narration_hash": incoming_hash,
        "narration_audio_path": str(audio_path.relative_to(project_dir)),
        "word_timestamps": timestamps,
        "scenes": [
            scene.to_dict()
            for scene in align_scenes(
                script["scenes"],
                timestamps,
                narration_duration_sec=narration_duration,
            )
        ],
    }
    write_manifest(project_dir / "build_manifest.json", manifest)
    write_manifest(variant_manifest_path(project_dir, script_path), manifest)
    state = new_state(script, now)
    write_project_state(project_state_path(project_dir), state)
    print(f"Generated narration: {audio_path}")
    print(f"Updated manifest: {project_dir / 'build_manifest.json'}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="creatortainment")
    commands = parser.add_subparsers(dest="command", required=True)
    validate = commands.add_parser("validate", help="Validate a script and all shared assets.")
    validate.add_argument("script", type=Path)
    validate.add_argument(
        "--asset-gen-info",
        action="store_true",
        help="Print effective generation models for generated assets.",
    )
    generate = commands.add_parser(
        "generate-assets",
        help="Generate missing assets declared by a script.",
    )
    generate.add_argument("script", type=Path)
    generate.add_argument(
        "--force",
        action="store_true",
        help="Regenerate assets even when their destination already exists.",
    )
    render = commands.add_parser("render", help="Render the script to an MP4 video.")
    render.add_argument("script", type=Path)
    render.add_argument("--out", type=Path, help="Output MP4 path relative to the project.")
    render.add_argument(
        "--preview",
        action="store_true",
        help="Render at quarter resolution with faster encoding settings.",
    )
    storyboard = commands.add_parser(
        "storyboard",
        help="Generate a fast visual storyboard PNG without narration or video rendering.",
    )
    storyboard.add_argument("script", type=Path)
    storyboard.add_argument("--out", type=Path, help="Output PNG path relative to the project.")
    align = commands.add_parser("align", help="Generate or reuse the full-video narration manifest.")
    align.add_argument("script", type=Path)
    align.add_argument("--force-audio", action="store_true", help="Always create a new narration without confirmation.")
    align.add_argument("--debug", action="store_true", help="Write detailed API diagnostics to the project debug.log.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "validate":
        return validate_command(args.script, args.asset_gen_info)
    if args.command == "generate-assets":
        return generate_assets_command(args.script, args.force)
    if args.command == "render":
        return render_command(args.script, args.out, args.preview)
    if args.command == "storyboard":
        return storyboard_command(args.script, args.out)
    if args.command == "align":
        return align_command(args.script, args.force_audio, args.debug)
    return 2
