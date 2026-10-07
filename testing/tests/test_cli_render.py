"""Tests that CLI preview and full-render paths choose exact output dimensions."""

from __future__ import annotations

from pathlib import Path
import json

from moviepy import ColorClip

from creatortainment.cli import prepare_render_clip, scale_script_for_preview
from creatortainment.schema.validate import load_script
from creatortainment import cli


def test_non_preview_render_keeps_project_resolution() -> None:
    """A normal render keeps the clip at the exact project resolution."""
    clip = ColorClip((1920, 1080), color=(0, 0, 0), duration=0.1)
    try:
        encoded = prepare_render_clip(clip, (1920, 1080), preview=False)
        assert encoded.size == (1920, 1080)
    finally:
        clip.close()


def test_preview_render_uses_quarter_resolution() -> None:
    """Preview rendering explicitly scales the clip to one-quarter resolution."""
    clip = ColorClip((480, 270), color=(0, 0, 0), duration=0.1)
    try:
        encoded = prepare_render_clip(clip, (1920, 1080), preview=True)
        assert encoded.size == (480, 270)
    finally:
        clip.close()


def test_preview_script_scales_canvas_positions_and_caption_sizes() -> None:
    """Preview preparation scales visual coordinates before frame rendering."""
    script = {
        "project": {
            "resolution": [1920, 1080],
            "caption_style": {"font_size": 64},
        },
        "scenes": [
            {
                "caption_style": {"font_size": 76},
                "elements": [
                    {"keyframes": [{"pos": [1330, 470]}]},
                ],
            }
        ],
    }
    preview = scale_script_for_preview(script)
    assert preview["project"]["resolution"] == [480, 270]
    assert preview["project"]["caption_style"]["font_size"] == 16
    assert preview["scenes"][0]["caption_style"]["font_size"] == 19
    assert preview["scenes"][0]["elements"][0]["keyframes"][0]["pos"] == [332.5, 117.5]
    assert script["project"]["resolution"] == [1920, 1080]


def test_preview_script_scales_typed_models() -> None:
    """Preview preparation also scales the Pydantic-backed script model."""
    script = load_script(
        Path("testing/scripts/example_script.json")
    )
    preview = scale_script_for_preview(script)
    assert preview["project"]["resolution"] == [270, 480]
    assert preview["project"]["caption_style"]["font_size"] == 16


def test_open_prompt_skips_noninteractive_stdin(monkeypatch, tmp_path: Path) -> None:
    opened: list[Path] = []
    monkeypatch.setattr("creatortainment.cli._stdin_is_interactive", lambda: False)
    monkeypatch.setattr("creatortainment.cli.open_with_default_application", opened.append)
    from creatortainment import cli

    cli._prompt_to_open_output(tmp_path / "video.mp4")
    assert opened == []


def test_open_prompt_accepts_yes_and_uses_exact_path(monkeypatch, tmp_path: Path) -> None:
    opened: list[Path] = []
    monkeypatch.setattr("creatortainment.cli._stdin_is_interactive", lambda: True)
    monkeypatch.setattr("builtins.input", lambda _prompt: "YeS")
    monkeypatch.setattr("creatortainment.cli.open_with_default_application", opened.append)
    from creatortainment import cli

    cli._prompt_to_open_output(tmp_path / "video.mp4")
    assert opened == [tmp_path / "video.mp4"]


def test_open_prompt_opens_for_default_and_skips_no(monkeypatch, tmp_path: Path) -> None:
    opened: list[Path] = []
    monkeypatch.setattr("creatortainment.cli._stdin_is_interactive", lambda: True)
    monkeypatch.setattr("creatortainment.cli.open_with_default_application", opened.append)
    from creatortainment import cli

    for answer in ("", "n", "no"):
        monkeypatch.setattr("builtins.input", lambda _prompt, answer=answer: answer)
        cli._prompt_to_open_output(tmp_path / "video.mp4")
    assert opened == [tmp_path / "video.mp4"]


def test_open_failure_is_nonfatal(monkeypatch, tmp_path: Path, capsys) -> None:
    monkeypatch.setattr("creatortainment.cli._stdin_is_interactive", lambda: True)
    monkeypatch.setattr("builtins.input", lambda _prompt: "y")
    monkeypatch.setattr("creatortainment.cli.open_with_default_application", lambda _path: False)

    from creatortainment import cli

    cli._prompt_to_open_output(tmp_path / "video.mp4")
    assert "could not open output" in capsys.readouterr().err


def test_open_uses_xdg_open_on_linux(monkeypatch, tmp_path: Path) -> None:
    calls: list[tuple[list[str], dict]] = []
    monkeypatch.setattr("creatortainment.cli.sys.platform", "linux")
    monkeypatch.setattr("creatortainment.cli.shutil.which", lambda name: "/usr/bin/xdg-open")
    monkeypatch.setattr(
        "creatortainment.cli.subprocess.Popen",
        lambda command, **kwargs: calls.append((command, kwargs)),
    )
    from creatortainment import cli

    assert cli.open_with_default_application(tmp_path / "video.mp4") is True
    assert calls[0][0] == ["/usr/bin/xdg-open", str(tmp_path / "video.mp4")]
    assert calls[0][1]["start_new_session"] is True
    assert "shell" not in calls[0][1]


def test_open_uses_open_on_macos(monkeypatch, tmp_path: Path) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr("creatortainment.cli.sys.platform", "darwin")
    monkeypatch.setattr(
        "creatortainment.cli.subprocess.Popen",
        lambda command, **_kwargs: calls.append(command),
    )
    from creatortainment import cli

    assert cli.open_with_default_application(tmp_path / "storyboard.png") is True
    assert calls == [["open", str(tmp_path / "storyboard.png")]]


def test_open_uses_startfile_on_windows(monkeypatch, tmp_path: Path) -> None:
    opened: list[str] = []
    monkeypatch.setattr("creatortainment.cli.sys.platform", "win32")
    monkeypatch.setattr("creatortainment.cli.os", type(
        "FakeOS", (), {"startfile": staticmethod(opened.append)}
    ))
    from creatortainment import cli

    assert cli.open_with_default_application(tmp_path / "video.mp4") is True
    assert opened == [str(tmp_path / "video.mp4")]


def test_missing_linux_opener_is_nonfatal(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("creatortainment.cli.sys.platform", "linux")
    monkeypatch.setattr("creatortainment.cli.shutil.which", lambda _name: None)
    from creatortainment import cli

    assert cli.open_with_default_application(tmp_path / "video.mp4") is False


def test_failed_render_does_not_prompt_or_open(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source = json.loads(
        Path("testing/scripts/example_script.json").read_text(encoding="utf-8")
    )
    source["scenes"][0]["bg"] = "missing_background"
    script_path = tmp_path / "invalid.json"
    script_path.write_text(json.dumps(source), encoding="utf-8")
    monkeypatch.setattr(cli, "ASSETS_ROOT", Path("testing/assets"))
    monkeypatch.setattr(cli, "_stdin_is_interactive", lambda: True)
    monkeypatch.setattr("builtins.input", lambda _prompt: "yes")
    opened: list[Path] = []
    monkeypatch.setattr(cli, "open_with_default_application", opened.append)

    assert cli.render_command(script_path, None, preview=True) == 1
    assert opened == []
