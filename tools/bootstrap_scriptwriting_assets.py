#!/usr/bin/env python3
"""Resumably curate production assets for the scriptwriting workspace."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "assets"
DEST = ROOT / "scriptwriting" / "assets"
STATE_PATH = DEST / ".bootstrap_state.json"


def _ffprobe(path: Path) -> dict[str, object]:
    result = subprocess.run(
        [
            "ffprobe", "-v", "error", "-show_streams", "-show_format",
            "-of", "json", str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    data = json.loads(result.stdout)
    streams = data.get("streams", [])
    video = next((item for item in streams if item.get("codec_type") == "video"), None)
    audio = next((item for item in streams if item.get("codec_type") == "audio"), None)
    result_data: dict[str, object] = {
        "duration_sec": float(data.get("format", {}).get("duration", 0) or 0),
        "has_audio": audio is not None,
    }
    if video:
        result_data["width"] = video.get("width")
        result_data["height"] = video.get("height")
        result_data["fps"] = video.get("r_frame_rate")
    return result_data


def _metadata(path: Path, relative: Path) -> dict[str, object]:
    suffix = path.suffix.lower()
    data: dict[str, object] = {
        "source": f"assets/{relative.as_posix()}",
        "type": suffix.lstrip(".") or "unknown",
        "size_bytes": path.stat().st_size,
    }
    if suffix in {".png", ".jpg", ".jpeg", ".webp", ".gif"}:
        with Image.open(path) as image:
            data.update(
                {
                    "width": image.width,
                    "height": image.height,
                    "mode": image.mode,
                    "frames": getattr(image, "n_frames", 1),
                    "has_transparency": "A" in image.getbands() or "transparency" in image.info,
                }
            )
    if suffix in {".gif", ".mp4", ".mov", ".webm", ".avi", ".mkv", ".mp3", ".wav", ".m4a"}:
        data.update(_ffprobe(path))
    return data


def _category(relative: Path) -> Path:
    if relative.parts[0] == "audio":
        return Path("audio") / ("sfx" if "sfx" in relative.parts else "music")
    return Path(relative.parts[0])


def _sidecar_text(metadata: dict[str, object], curated: Path) -> str:
    source = metadata["source"]
    kind = metadata["type"]
    dimensions = (
        f"{metadata.get('width')}×{metadata.get('height')}"
        if "width" in metadata else "audio asset"
    )
    duration = (
        f"{metadata['duration_sec']:.3f}s at {metadata.get('fps', 'unknown')} fps"
        if metadata.get("duration_sec") else "duration not reported"
    )
    category = curated.parent.as_posix()
    purposes = {
        "backgrounds": "scene backgrounds, mood-setting, establishing shots, transitions, and visual texture",
        "images": "explanatory inserts, diagrams, screenshots, props, and visual evidence",
        "sprites": "character reactions, presenters, gestures, visual punctuation, and recurring mascots",
        "audio/music": "music beds, pacing, mood, montage support, and transitions",
        "audio/sfx": "impact cues, reveals, interface actions, comedic punctuation, and scene transitions",
    }.get(category, "reusable scene support and visual or audio design")
    return f"""# {curated.name}

## What it is

Curated `{kind}` asset from the production library (`{source}`).

## Observed properties

- Dimensions/type: {dimensions}
- Duration: {duration}
- Audio stream: {metadata.get('has_audio', 'not applicable')}
- Transparency: {metadata.get('has_transparency', 'not applicable')}

## Useful purposes

Review the visual/audio content before assigning a specific scene purpose.
Potential uses for this category include {purposes}.

## Pairings and cautions

Pair with related assets listed in the category index. Confirm aspect ratio,
visual style, and narrative purpose before use. Do not assume this asset is
appropriate for every script merely because it is in this category.

## Provenance

- Production source: `{source}`
- Curated path: `scriptwriting/assets/{curated.as_posix()}`
- Bootstrap metadata is mechanical; add human visual notes after inspection.
"""


def _inspect_frames(source: Path, curated: Path) -> list[str]:
    if source.suffix.lower() not in {".gif", ".mp4", ".webm", ".mov", ".mkv"}:
        return []
    output_dir = curated.parent / ".inspection" / curated.stem
    output_dir.mkdir(parents=True, exist_ok=True)
    outputs = [output_dir / "frame_00.jpg", output_dir / "frame_50.jpg", output_dir / "frame_99.jpg"]
    probe = _ffprobe(source)
    duration = float(probe.get("duration_sec", 0) or 0)
    for timestamp, output in zip((0.0, duration / 2, max(0.0, duration - 0.05)), outputs):
        subprocess.run(
            [
                "ffmpeg", "-y", "-loglevel", "error", "-ss", f"{timestamp:.3f}",
                "-i", str(source), "-frames:v", "1", "-vf", "scale=640:-1",
                str(output),
            ],
            check=True,
        )
    return [str(item.relative_to(DEST)) for item in outputs if item.is_file()]


def _write_indexes(inventory: dict[str, dict[str, object]]) -> None:
    categories = sorted({_category(Path(source)) for source in inventory})
    for category in categories:
        category_dir = DEST / category
        category_dir.mkdir(parents=True, exist_ok=True)
        assets = sorted(
            Path(record["curated"])
            for source, record in inventory.items()
            if Path(record["curated"]).parent == category
        )
        lines = [
            f"# {category.as_posix().replace('/', ' / ').title()}",
            "",
            "This category contains curated reusable assets from the production library.",
            "Use these assets for future scenes whose visual or audio purpose fits;",
            "the original script is not the only intended use.",
            "",
            "## Assets",
            "",
        ]
        lines.extend(
            f"- [{asset.name}]({asset.name}) — "
            f"[sidecar]({asset.name}.md)"
            for asset in assets
        )
        lines.extend(
            [
                "",
                "## Related categories",
                "",
                "- See the [global asset index](../../ASSET_INDEX.md).",
                "- Check adjacent categories before concluding an asset is unavailable.",
                "",
            ]
        )
        (category_dir / "INDEX.md").write_text("\n".join(lines), encoding="utf-8")
    categories_text = [
        "# Curated asset index",
        "",
        "Generated from the resumable production asset inventory. Discover assets progressively:",
        "`global index → category INDEX.md → individual asset sidecar`.",
        "",
        "The production `assets/` directory is authoritative; these are curated copies.",
        "Assets have one physical location but may be conceptually useful across categories;",
        "follow related indexes before concluding that an asset is unavailable.",
        "",
        "## Categories",
        "",
    ]
    categories_text.extend(
        f"- [{category.as_posix()}]({(Path('assets') / category / 'INDEX.md').as_posix()})"
        for category in categories
    )
    (DEST.parent / "ASSET_INDEX.md").write_text("\n".join(categories_text) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--inspect-frames", action="store_true")
    args = parser.parse_args()
    DEST.mkdir(parents=True, exist_ok=True)
    state = json.loads(STATE_PATH.read_text()) if STATE_PATH.is_file() else {}
    inventory: dict[str, dict[str, object]] = {}
    for source in sorted(path for path in SOURCE.rglob("*") if path.is_file()):
        relative = source.relative_to(SOURCE)
        if relative.parts[0] == "testing" or source.name == ".gitkeep":
            continue
        category = _category(relative)
        curated = DEST / category / source.name
        key = relative.as_posix()
        metadata = _metadata(source, relative)
        fingerprint = f"{metadata['size_bytes']}:{source.stat().st_mtime_ns}"
        record = state.get(key, {})
        if args.refresh or record.get("fingerprint") != fingerprint or not curated.is_file():
            curated.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, curated)
            sidecar = curated.with_suffix(curated.suffix + ".md")
            sidecar.write_text(_sidecar_text(metadata, category / source.name), encoding="utf-8")
            inspected = _inspect_frames(source, curated) if args.inspect_frames else record.get("inspection", [])
            state[key] = {"fingerprint": fingerprint, "curated": str(curated.relative_to(DEST)), "inspection": inspected}
        metadata["curated"] = str(category / source.name)
        inventory[key] = metadata
    state = {key: state[key] for key in inventory if key in state}
    (DEST / "inventory.json").write_text(json.dumps(inventory, indent=2, sort_keys=True) + "\n")
    STATE_PATH.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")
    _write_indexes(inventory)
    print(f"Curated {len(inventory)} production assets into {DEST}")
    print(f"Resumability state: {STATE_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
