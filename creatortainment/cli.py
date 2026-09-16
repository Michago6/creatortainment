"""Command-line interface for Creatortainment."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

from .render.mock import render_storyboard, write_manifest
from .audio.elevenlabs_client import NarrationResult, WordTimestamp
from .audio.manifest import build_manifest
from .schema.validate import load_script, validate_script


REPO_ROOT = Path(__file__).resolve().parents[1]
ASSETS_ROOT = REPO_ROOT / "assets"
PROJECTS_ROOT = REPO_ROOT / "projects"


def project_slug(title: str) -> str:
    value = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return value or "untitled-project"


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


def render_command(script_path: Path, output: Path | None) -> int:
    script = load_script(script_path)
    result = validate_script(script, ASSETS_ROOT)
    if not result.valid:
        print("Cannot render an invalid script:", file=sys.stderr)
        for error in result.errors:
            print(f"- {error}", file=sys.stderr)
        return 1

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    project_dir = PROJECTS_ROOT / f"{project_slug(script['project']['title'])}-{timestamp}"
    project_dir.mkdir(parents=True, exist_ok=False)
    shutil.copy2(script_path, project_dir / "script.json")
    destination = output or (project_dir / "output" / "storyboard.png")
    if not destination.is_absolute():
        destination = project_dir / destination
    render_storyboard(script, ASSETS_ROOT, destination)
    write_manifest(script, project_dir, destination)
    print(f"Created project: {project_dir}")
    print(f"Mock render: {destination}")
    return 0


class FixtureNarrationClient:
    def __init__(self, fixture_path: Path) -> None:
        self.fixture_path = fixture_path
        self.calls = 0

    def synthesize(self, scenes: list[dict]) -> NarrationResult:
        self.calls += 1
        payload = json.loads(self.fixture_path.read_text(encoding="utf-8"))
        timestamps = payload["word_timestamps"] if isinstance(payload, dict) else payload
        return NarrationResult(
            audio_bytes=b"mock narration audio",
            word_timestamps=[WordTimestamp(**item) for item in timestamps],
            pause_before_sec=[],
        )


def align_command(script_path: Path, mock_response: Path | None) -> int:
    script = load_script(script_path)
    result = validate_script(script, ASSETS_ROOT)
    if not result.valid:
        print("Cannot align an invalid script:", file=sys.stderr)
        for error in result.errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    project_dir = PROJECTS_ROOT / f"{project_slug(script['project']['title'])}-{timestamp}"
    project_dir.mkdir(parents=True, exist_ok=False)
    shutil.copy2(script_path, project_dir / "script.json")
    if mock_response is not None:
        client = FixtureNarrationClient(mock_response)
    else:
        from .audio.elevenlabs_client import ElevenLabsNarrationClient

        api_key = os.environ.get("ELEVENLABS_API_KEY")
        voice_id = os.environ.get("ELEVENLABS_VOICE_ID")
        if not api_key or not voice_id:
            raise RuntimeError(
                "Set ELEVENLABS_API_KEY and ELEVENLABS_VOICE_ID, or pass --mock-response."
            )
        client = ElevenLabsNarrationClient(api_key, voice_id=voice_id)
    manifest, cached = build_manifest(script, project_dir / "build_manifest.json", client)
    print(f"{'Cache hit' if cached else 'Generated'} manifest: {project_dir / 'build_manifest.json'}")
    print(f"Scenes aligned: {len(manifest['scenes'])}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="creatortainment")
    commands = parser.add_subparsers(dest="command", required=True)
    validate = commands.add_parser("validate", help="Validate a script and all shared assets.")
    validate.add_argument("script", type=Path)
    render = commands.add_parser("render", help="Create a project and render a mock storyboard.")
    render.add_argument("script", type=Path)
    render.add_argument("--out", type=Path, help="Output PNG path relative to the new project.")
    align = commands.add_parser("align", help="Generate or reuse the full-video narration manifest.")
    align.add_argument("script", type=Path)
    align.add_argument("--mock-response", type=Path, help="Offline timestamp fixture JSON.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "validate":
        return validate_command(args.script)
    if args.command == "render":
        return render_command(args.script, args.out)
    if args.command == "align":
        return align_command(args.script, args.mock_response)
    return 2
