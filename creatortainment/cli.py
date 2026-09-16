"""Command-line interface for Creatortainment."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

from .render.mock import render_storyboard, write_manifest
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="creatortainment")
    commands = parser.add_subparsers(dest="command", required=True)
    validate = commands.add_parser("validate", help="Validate a script and all shared assets.")
    validate.add_argument("script", type=Path)
    render = commands.add_parser("render", help="Create a project and render a mock storyboard.")
    render.add_argument("script", type=Path)
    render.add_argument("--out", type=Path, help="Output PNG path relative to the new project.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "validate":
        return validate_command(args.script)
    if args.command == "render":
        return render_command(args.script, args.out)
    return 2
