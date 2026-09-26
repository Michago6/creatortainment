"""Focused offline checks for the scriptwriting workspace boundary."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).parents[2]
WORKSPACE = ROOT / "scriptwriting"


def test_scriptwriting_workspace_is_ignored_and_has_lifecycle() -> None:
    ignored = subprocess.run(
        ["git", "check-ignore", "--quiet", "scriptwriting/AGENTS.md"],
        cwd=ROOT,
    )
    assert ignored.returncode == 0
    assert all((WORKSPACE / "scripts" / state).is_dir() for state in ("drafts", "ready", "archive"))


def test_progressive_asset_indexes_and_sidecars_exist() -> None:
    global_index = WORKSPACE / "ASSET_INDEX.md"
    category_index = WORKSPACE / "assets" / "backgrounds" / "INDEX.md"
    asset = WORKSPACE / "assets" / "backgrounds" / "default_studio.jpg"
    assert global_index.is_file()
    assert category_index.is_file()
    assert asset.with_name(asset.name + ".md").is_file()
    assert "global index" in global_index.read_text(encoding="utf-8")
    assert "default_studio.jpg" in category_index.read_text(encoding="utf-8")


def test_bootstrap_inventory_is_resumable_and_contains_media_metadata() -> None:
    inventory = json.loads(
        (WORKSPACE / "assets" / "inventory.json").read_text(encoding="utf-8")
    )
    state = json.loads(
        (WORKSPACE / "assets" / ".bootstrap_state.json").read_text(encoding="utf-8")
    )
    assert len(inventory) == len(state) == 106
    assert "width" in inventory["backgrounds/default_studio.jpg"]
    assert "fingerprint" in state["backgrounds/default_studio.jpg"]
    assert (
        WORKSPACE / "assets" / "backgrounds" / ".inspection" / "mandelbrot_zoom_1" / "frame_50.jpg"
    ).is_file()


def test_bootstrap_inventory_uses_canonical_paths_and_state_fingerprints() -> None:
    inventory = json.loads(
        (WORKSPACE / "assets" / "inventory.json").read_text(encoding="utf-8")
    )
    state = json.loads(
        (WORKSPACE / "assets" / ".bootstrap_state.json").read_text(encoding="utf-8")
    )

    assert "audio/monkeys_spinning_monkeys.mp3" in inventory
    assert inventory["audio/monkeys_spinning_monkeys.mp3"]["curated"] == (
        "audio/monkeys_spinning_monkeys.mp3"
    )
    assert "sprites/mrmouse_withbg/mrmouse_relaxed.png" in inventory
    assert state["audio/monkeys_spinning_monkeys.mp3"]["fingerprint"]
    assert not (WORKSPACE / "assets" / "audio" / "music").exists()
