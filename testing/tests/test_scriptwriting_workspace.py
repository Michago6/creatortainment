"""Focused offline checks for the scriptwriting workspace boundary."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import importlib.util
from pathlib import Path

ROOT = Path(__file__).parents[2]
WORKSPACE = ROOT / "scriptwriting"
TEMPLATE = ROOT / "scriptwriting_template"
TEST_ASSETS = ROOT / "testing/assets"


def test_scriptwriting_workspace_is_ignored_and_has_lifecycle(tmp_path: Path) -> None:
    git_dir = subprocess.run(
        ["git", "rev-parse", "--is-inside-work-tree"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if git_dir.returncode == 0:
        ignored = subprocess.run(
            ["git", "check-ignore", "--quiet", "scriptwriting/AGENTS.md"],
            cwd=ROOT,
        )
        assert ignored.returncode == 0
    workspace = tmp_path / "scriptwriting"
    shutil.copytree(TEMPLATE, workspace)
    assert all(
        (workspace / "scripts" / state).is_dir()
        for state in ("drafts", "archive")
    )
    assert not (workspace / "scripts" / "ready").exists()


def _load_bootstrap_module():
    path = ROOT / "tools/bootstrap_scriptwriting_assets.py"
    spec = importlib.util.spec_from_file_location("bootstrap_scriptwriting_assets", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_progressive_asset_indexes_and_sidecars_exist(tmp_path: Path, monkeypatch) -> None:
    workspace = tmp_path / "scriptwriting"
    shutil.copytree(TEMPLATE, workspace)
    shutil.copytree(TEST_ASSETS, workspace / "assets", dirs_exist_ok=True)

    bootstrap = _load_bootstrap_module()
    monkeypatch.setattr(bootstrap, "DEST", workspace / "assets")
    monkeypatch.setattr(bootstrap, "STATE_PATH", workspace / "assets/.bootstrap_state.json")
    monkeypatch.setattr(sys, "argv", ["bootstrap_scriptwriting_assets.py"])

    assert bootstrap.main() == 0

    global_index = workspace / "ASSET_INDEX.md"
    category_index = workspace / "assets" / "backgrounds" / "INDEX.md"
    asset = workspace / "assets" / "backgrounds" / "default_studio.jpg"
    assert global_index.is_file()
    assert category_index.is_file()
    assert asset.with_name(asset.name + ".md").is_file()
    assert "global index" in global_index.read_text(encoding="utf-8")
    assert "default_studio.jpg" in category_index.read_text(encoding="utf-8")


def test_bootstrap_inventory_is_resumable_and_contains_media_metadata(
    tmp_path: Path,
    monkeypatch,
) -> None:
    workspace = tmp_path / "scriptwriting"
    shutil.copytree(TEMPLATE, workspace)
    shutil.copytree(TEST_ASSETS, workspace / "assets", dirs_exist_ok=True)

    bootstrap = _load_bootstrap_module()
    monkeypatch.setattr(bootstrap, "DEST", workspace / "assets")
    monkeypatch.setattr(bootstrap, "STATE_PATH", workspace / "assets/.bootstrap_state.json")
    monkeypatch.setattr(sys, "argv", ["bootstrap_scriptwriting_assets.py", "--inspect-frames"])

    assert bootstrap.main() == 0
    inventory = json.loads(
        (workspace / "assets" / "inventory.json").read_text(encoding="utf-8")
    )
    state = json.loads(
        (workspace / "assets" / ".bootstrap_state.json").read_text(encoding="utf-8")
    )
    assert inventory
    assert inventory.keys() == state.keys()
    assert "width" in inventory["backgrounds/default_studio.jpg"]
    assert "fingerprint" in state["backgrounds/default_studio.jpg"]
    inspected_files = list(
        (workspace / "assets").glob("**/.inspection/*/frame_*.jpg")
    )
    assert inspected_files


def test_bootstrap_inventory_uses_canonical_paths_and_state_fingerprints(
    tmp_path: Path,
    monkeypatch,
) -> None:
    workspace = tmp_path / "scriptwriting"
    shutil.copytree(TEMPLATE, workspace)
    shutil.copytree(TEST_ASSETS, workspace / "assets", dirs_exist_ok=True)

    bootstrap = _load_bootstrap_module()
    monkeypatch.setattr(bootstrap, "DEST", workspace / "assets")
    monkeypatch.setattr(bootstrap, "STATE_PATH", workspace / "assets/.bootstrap_state.json")
    monkeypatch.setattr(sys, "argv", ["bootstrap_scriptwriting_assets.py"])

    assert bootstrap.main() == 0
    inventory = json.loads(
        (workspace / "assets" / "inventory.json").read_text(encoding="utf-8")
    )
    state = json.loads(
        (workspace / "assets" / ".bootstrap_state.json").read_text(encoding="utf-8")
    )

    assert "audio/monkeys_spinning_monkeys.mp3" in inventory
    assert inventory["audio/monkeys_spinning_monkeys.mp3"]["curated"] == (
        "audio/monkeys_spinning_monkeys.mp3"
    )
    assert not any(key.startswith("sprites/mrmouse_") and "/with" in key for key in inventory)
    assert state["audio/monkeys_spinning_monkeys.mp3"]["fingerprint"]
    assert not (WORKSPACE / "assets" / "audio" / "music").exists()
