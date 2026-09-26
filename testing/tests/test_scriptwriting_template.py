"""Focused offline checks for the public scriptwriting template."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).parents[2]
TEMPLATE = ROOT / "scriptwriting_template"


def test_template_has_public_workspace_layout() -> None:
    expected_files = (
        "AGENTS.md",
        "ASSET_INDEX.md",
        "docs/SCRIPT_STRUCTURE.md",
        "docs/SCRIPT_CONVENTIONS.md",
        "docs/ASSET_LIBRARY_GUIDELINES.md",
        "docs/AGENT_SETUP.md",
        "agent_knowledge/INDEX.md",
    )
    expected_dirs = (
        "assets",
        "scripts/drafts",
        "scripts/ready",
        "scripts/archive",
        "agent_knowledge/writing",
        "agent_knowledge/visuals",
        "agent_knowledge/models",
        "agent_knowledge/lessons",
    )
    assert all((TEMPLATE / path).is_file() for path in expected_files)
    assert all((TEMPLATE / path).is_dir() for path in expected_dirs)


def test_template_contains_only_placeholders_in_assets_and_knowledge() -> None:
    asset_files = [path for path in (TEMPLATE / "assets").rglob("*") if path.is_file()]
    knowledge_files = [path for path in (TEMPLATE / "agent_knowledge").rglob("*") if path.is_file()]
    assert asset_files == [TEMPLATE / "assets" / ".gitkeep"]
    assert set(knowledge_files) == {
        TEMPLATE / "agent_knowledge" / "INDEX.md",
        TEMPLATE / "agent_knowledge" / "writing" / ".gitkeep",
        TEMPLATE / "agent_knowledge" / "visuals" / ".gitkeep",
        TEMPLATE / "agent_knowledge" / "models" / ".gitkeep",
        TEMPLATE / "agent_knowledge" / "lessons" / ".gitkeep",
    }


def test_template_docs_use_current_direct_cli_and_generic_content() -> None:
    docs = "\n".join(path.read_text(encoding="utf-8") for path in (TEMPLATE / "docs").glob("*.md"))
    agents = (TEMPLATE / "AGENTS.md").read_text(encoding="utf-8")
    index = (TEMPLATE / "ASSET_INDEX.md").read_text(encoding="utf-8")
    combined = f"{agents}\n{index}\n{docs}"
    assert ".venv/bin/python -m creatortainment validate" in combined
    assert ".venv/bin/python -m creatortainment storyboard" in combined
    assert "workflow/context boundary, not a security boundary" in combined
    assert "bwrap" not in combined.lower()
    assert "broker" not in combined.lower()
    assert "mrmouse" not in combined.lower()
    assert "scriptwriting/assets/" in combined
    assert "ASSET_INDEX.md" in combined
