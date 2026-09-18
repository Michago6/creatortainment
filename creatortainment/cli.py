"""Command-line interface for Creatortainment."""

from __future__ import annotations

import argparse
import copy
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

from .audio.alignment import align_scenes
from .audio.elevenlabs_client import ElevenLabsNarrationClient
from .audio.manifest import DEFAULT_TTS_MODEL, narration_hash, read_manifest, write_manifest
from .project_identity import (
    new_state,
    project_state_path,
    read_project_state,
    slugify,
    variant_manifest_path,
    write_project_state,
)
from .render.moviepy_scene import build_full_video_clip
from .schema.validate import load_script, validate_script


REPO_ROOT = Path(__file__).resolve().parents[1]
ASSETS_ROOT = REPO_ROOT / "assets"
PROJECTS_ROOT = REPO_ROOT / "projects"
ELEVENLABS_API_KEY_PATH = REPO_ROOT / "elevenlabs_api_key.txt"


def scale_script_for_preview(script: dict) -> dict:
    """Scale canvas coordinates and caption sizes before preview rendering."""
    scaled = copy.deepcopy(script)
    width, height = (int(value) for value in script["project"]["resolution"])
    preview_width = max(1, round(width * 0.25))
    preview_height = max(1, round(height * 0.25))
    scaled["project"]["resolution"] = [preview_width, preview_height]

    project_style = scaled["project"].get("caption_style")
    if isinstance(project_style, dict) and "font_size" in project_style:
        project_style["font_size"] = max(1, round(float(project_style["font_size"]) * 0.25))
    for scene in scaled.get("scenes", []):
        scene_style = scene.get("caption_style")
        if isinstance(scene_style, dict) and "font_size" in scene_style:
            scene_style["font_size"] = max(1, round(float(scene_style["font_size"]) * 0.25))
        for element in scene.get("elements", []):
            for keyframe in element.get("keyframes", []):
                if isinstance(keyframe.get("pos"), list) and len(keyframe["pos"]) == 2:
                    keyframe["pos"] = [
                        float(keyframe["pos"][0]) * 0.25,
                        float(keyframe["pos"][1]) * 0.25,
                    ]
    return scaled


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


def validate_command(script_path: Path) -> int:
    script = load_script(script_path)
    result = validate_script(script, ASSETS_ROOT)
    if result.valid:
        print(f"Valid: {script_path}")
        return 0
    print(f"Invalid: {script_path}", file=sys.stderr)
    for error in result.errors:
        print(f"- {error}", file=sys.stderr)
    return 1


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
    destination = output or (project_dir / "output" / "video.mp4")
    if not destination.is_absolute():
        destination = project_dir / destination
    manifest_path = variant_manifest_path(project_dir, script_path)
    if not manifest_path.is_file():
        manifest_path = project_dir / "build_manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(
            f"No build manifest found for {script_path}. "
            "Run align for this script before rendering."
        )
    manifest = read_manifest(manifest_path)
    render_script = scale_script_for_preview(script) if preview else script
    clip = build_full_video_clip(render_script, manifest, ASSETS_ROOT, project_dir)
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
    return 0


def read_api_key(path: Path) -> str:
    if not path.is_file():
        raise RuntimeError(
            f"ElevenLabs API key file not found: {path}. "
            "Create this file with the API key on its first non-empty line."
        )
    for line in path.read_text(encoding="utf-8").splitlines():
        value = line.strip()
        if value and not value.startswith("#"):
            return value
    raise RuntimeError(f"ElevenLabs API key file is empty: {path}")


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
    from moviepy import AudioFileClip

    audio = AudioFileClip(str(audio_path))
    try:
        final_end = max(
            (float(scene["end_time_sec"]) for scene in manifest.get("scenes", [])),
            default=0.0,
        )
        if final_end <= audio.duration + 0.001:
            return False
    finally:
        audio.close()

    timestamps = manifest.get("word_timestamps")
    if not isinstance(timestamps, list):
        raise ValueError(f"Cached manifest has no usable word_timestamps: {manifest_path}")
    manifest["scenes"] = [
        scene.to_dict() for scene in align_scenes(script["scenes"], timestamps)
    ]
    write_manifest(manifest_path, manifest)
    return True


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
    existing = project_dir.exists()
    api_key = read_api_key(ELEVENLABS_API_KEY_PATH)
    voice_id = script["project"].get("voice_id")
    if not isinstance(voice_id, str) or not voice_id.strip():
        raise RuntimeError(
            "project.voice_id is required in the input script and must contain an ElevenLabs voice ID."
        )
    if existing and not force_audio:
        state = read_project_state(project_state_path(project_dir))
        print(f"A project named '{title}' already exists (last updated {state.get('updated_at', 'unknown')}).")
        same = state.get("narration_hash") == incoming_hash
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
        if same:
            legacy_manifest = project_dir / "build_manifest.json"
            variant_path = variant_manifest_path(project_dir, script_path)
            if legacy_manifest.is_file() and not variant_path.is_file():
                variant_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(legacy_manifest, variant_path)
            if variant_path.is_file():
                manifest_path = variant_path
            elif legacy_manifest.is_file():
                manifest_path = legacy_manifest
            else:
                raise FileNotFoundError(
                    f"Cached narration manifest not found in {project_dir}."
                )
            repaired = repair_cached_manifest_timing(script, manifest_path, project_dir)
            state.update({"title": title, "date": script["project"].get("date"), "updated_at": datetime.now(timezone.utc).isoformat()})
            write_project_state(project_state_path(project_dir), state)
            if repaired:
                print("Cached manifest timing was repaired from the existing narration.")
            print("Project metadata updated; existing narration remains active.")
            return 0
    elif not existing:
        project_dir.mkdir(parents=True, exist_ok=True)
        write_project_state(project_state_path(project_dir), new_state(script))

    project_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(script_path, project_dir / "script.json")
    model = script["project"].get("tts_model", DEFAULT_TTS_MODEL)
    result = ElevenLabsNarrationClient(
        api_key,
        voice_id=voice_id,
        model_id=model,
        debug_log=debug_log,
    ).synthesize(script["scenes"])
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
    sidecar_path.write_text(json.dumps({
        "narration_text": " ".join(scene["narration_text"].strip() for scene in script["scenes"]),
        "tts_model": model,
        "word_timestamps": timestamps,
        "created_at": now.isoformat(),
    }, indent=2) + "\n", encoding="utf-8")
    manifest = {
        "narration_hash": incoming_hash,
        "narration_audio_path": str(audio_path.relative_to(project_dir)),
        "word_timestamps": timestamps,
        "scenes": [scene.to_dict() for scene in align_scenes(script["scenes"], timestamps)],
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
    render = commands.add_parser("render", help="Render the script to an MP4 video.")
    render.add_argument("script", type=Path)
    render.add_argument("--out", type=Path, help="Output MP4 path relative to the project.")
    render.add_argument(
        "--preview",
        action="store_true",
        help="Render at quarter resolution with faster encoding settings.",
    )
    align = commands.add_parser("align", help="Generate or reuse the full-video narration manifest.")
    align.add_argument("script", type=Path)
    align.add_argument("--force-audio", action="store_true", help="Always create a new narration without confirmation.")
    align.add_argument("--debug", action="store_true", help="Write detailed API diagnostics to the project debug.log.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "validate":
        return validate_command(args.script)
    if args.command == "render":
        return render_command(args.script, args.out, args.preview)
    if args.command == "align":
        return align_command(args.script, args.force_audio, args.debug)
    return 2
