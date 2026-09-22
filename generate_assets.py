#!/usr/bin/env python3
"""Generate all image assets described by a JSON manifest.

The manifest is intentionally simple. It can be either:

{
  "assets": [
    {
      "name": "img_pacman_gameplay",
      "description": "A detailed image-generation prompt...",
      "path": "assets/images/pacman_classic_gameplay.jpg"
    }
  ]
}

or the existing format:

{
  "image_prompts": {
    "img_pacman_gameplay": "A detailed prompt..."
  }
}

When using the existing video script as the source of paths, pass:
    python scripts/generate_assets.py scripts/pac-man-ghosts-were-never-smart.json

If the prompt manifest is separate, pass:
    python scripts/generate_assets.py scripts/pac-man-ghosts-were-never-smart.json \
        --prompts scripts/pacman_image_prompts.json

Asset paths are resolved relative to the shared repository root. Use
--project-root to select that repository root when invoking this utility
outside the repository directory.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

MODEL_ID = "fal-ai/sana"
API_URL = f"https://fal.run/{MODEL_ID}"


def request_json(
    url: str,
    *,
    headers: dict[str, str],
    body: bytes | None = None,
) -> dict:
    request = Request(
        url,
        data=body,
        headers=headers,
        method="POST" if body else "GET",
    )
    try:
        with urlopen(request, timeout=300) as response:
            payload = json.loads(response.read())
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace").strip()
        raise RuntimeError(
            f"fal.ai request failed ({exc.code}): {detail[:500]}"
        ) from exc
    except URLError as exc:
        raise RuntimeError(
            f"Could not connect to fal.ai: {exc.reason}"
        ) from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError("fal.ai returned invalid JSON.") from exc

    if not isinstance(payload, dict):
        raise RuntimeError("fal.ai returned an unexpected response.")

    return payload


def generate_image(
    api_key: str,
    prompt: str,
    output_path: Path,
    *,
    width: int,
    height: int,
) -> None:
    body = json.dumps(
        {
            "prompt": prompt,
            "image_size": {
                "width": width,
                "height": height,
            },
        }
    ).encode("utf-8")

    result = request_json(
        API_URL,
        headers={
            "Authorization": f"Key {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        body=body,
    )

    images = result.get("images")
    if not isinstance(images, list) or not images:
        raise RuntimeError(
            "fal.ai response did not contain a generated image."
        )

    image_url = images[0].get("url") if isinstance(images[0], dict) else None
    if not isinstance(image_url, str) or not image_url:
        raise RuntimeError(
            "fal.ai response did not contain a usable image URL."
        )

    try:
        with urlopen(Request(image_url), timeout=300) as response:
            output_path.write_bytes(response.read())
    except HTTPError as exc:
        raise RuntimeError(
            f"Could not download the generated image ({exc.code})."
        ) from exc
    except URLError as exc:
        raise RuntimeError(
            f"Could not download the generated image: {exc.reason}"
        ) from exc


def read_api_key(path: Path) -> str:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise RuntimeError(
            f"Could not read API key file {path}: {exc}"
        ) from exc

    for line in lines:
        key = line.strip()
        if key and not key.startswith("#"):
            return key

    raise RuntimeError(f"API key file {path} is empty.")


def load_json(path: Path) -> dict:
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except OSError as exc:
        raise RuntimeError(f"Could not read JSON file {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"Invalid JSON in {path}: line {exc.lineno}, column {exc.colno}: "
            f"{exc.msg}"
        ) from exc

    if not isinstance(data, dict):
        raise RuntimeError(f"{path} must contain a JSON object.")

    return data


def load_prompt_manifest(path: Path) -> dict[str, str]:
    data = load_json(path)

    # Preferred standalone format:
    #
    # {
    #   "assets": [
    #     {
    #       "name": "...",
    #       "description": "...",
    #       "path": "..."
    #     }
    #   ]
    # }
    assets = data.get("assets")
    if isinstance(assets, list):
        prompts: dict[str, str] = {}

        for index, item in enumerate(assets):
            if not isinstance(item, dict):
                raise RuntimeError(
                    f"{path}: assets[{index}] must be an object."
                )

            name = item.get("name")
            description = item.get("description")

            if not isinstance(name, str) or not name.strip():
                raise RuntimeError(
                    f"{path}: assets[{index}] is missing a non-empty 'name'."
                )

            if not isinstance(description, str) or not description.strip():
                # Also accept "prompt" for convenience.
                description = item.get("prompt")

            if not isinstance(description, str) or not description.strip():
                raise RuntimeError(
                    f"{path}: asset '{name}' needs 'description' or 'prompt'."
                )

            prompts[name.strip()] = description.strip()

        return prompts

    # Existing format:
    #
    # {
    #   "image_prompts": {
    #       "asset_name": "prompt"
    #   }
    # }
    image_prompts = data.get("image_prompts")
    if isinstance(image_prompts, dict):
        prompts = {}
        for name, prompt in image_prompts.items():
            if not isinstance(name, str) or not isinstance(prompt, str):
                raise RuntimeError(
                    f"{path}: image_prompts must map asset names to strings."
                )
            prompts[name] = prompt.strip()
        return prompts

    raise RuntimeError(
        f"{path} does not contain 'assets' or 'image_prompts'."
    )


def load_script_assets(path: Path) -> dict[str, str]:
    data = load_json(path)
    registry = data.get("asset_registry")

    if not isinstance(registry, dict):
        raise RuntimeError(
            f"{path} does not contain an 'asset_registry' object."
        )

    assets: dict[str, str] = {}
    for name, entry in registry.items():
        if (
            not isinstance(name, str)
            or not isinstance(entry, dict)
            or not isinstance(entry.get("path"), str)
        ):
            raise RuntimeError(
                f"{path}: asset_registry must map names to objects with path strings."
            )
        assets[name] = entry["path"]

    return assets


def discover_prompt_file(script_path: Path) -> Path | None:
    candidates = [
        script_path.with_name(f"{script_path.stem}_image_prompts.json"),
        script_path.with_name("image_prompts.json"),
    ]

    for candidate in candidates:
        if candidate.is_file():
            return candidate

    # Also support a single *_image_prompts.json file beside the script.
    # This handles names such as pacman_image_prompts.json.
    candidates = sorted(script_path.parent.glob("*_image_prompts.json"))
    if len(candidates) == 1:
        return candidates[0]

    return None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate image assets from a video script and prompt manifest."
    )
    parser.add_argument(
        "script",
        type=Path,
        help="Video script JSON containing asset_registry.",
    )
    parser.add_argument(
        "--prompts",
        type=Path,
        help=(
            "Prompt manifest JSON. If omitted, the script itself is checked "
            "for image_prompts, then <script>_image_prompts.json, then "
            "image_prompts.json."
        ),
    )
    parser.add_argument(
        "--project-root",
        type=Path,
        default=Path.cwd(),
        help=(
            "Resolve asset paths relative to this directory "
            "(default: current working directory / project root)."
        ),
    )
    parser.add_argument(
        "--api-key-file",
        type=Path,
        default=Path("fal_api_key.txt"),
        help="fal.ai API key file, relative to the current working directory.",
    )
    parser.add_argument(
        "--width",
        type=int,
        default=1080,
        help="Generated image width (default: 1080).",
    )
    parser.add_argument(
        "--height",
        type=int,
        default=1920,
        help="Generated image height (default: 1920).",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.0,
        help="Seconds to wait between generation requests.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Regenerate images even if the destination already exists.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be generated without calling fal.ai.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    if args.width <= 0 or args.height <= 0:
        raise ValueError("Width and height must be positive.")

    script_path = args.script.resolve()
    if not script_path.is_file():
        raise RuntimeError(f"Script file does not exist: {script_path}")

    script_data = load_json(script_path)
    registry = script_data.get("asset_registry")
    if not isinstance(registry, dict):
        raise RuntimeError(
            f"{script_path} does not contain an 'asset_registry' object."
        )

    # 1. Explicit prompt manifest.
    prompt_path: Path | None = None
    prompts: dict[str, str] | None = None

    if args.prompts is not None:
        prompt_path = args.prompts.resolve()
        if not prompt_path.is_file():
            raise RuntimeError(
                f"Prompt manifest does not exist: {prompt_path}"
            )
        prompts = load_prompt_manifest(prompt_path)

    # 2. Embedded image_prompts.
    if prompts is None and isinstance(script_data.get("image_prompts"), dict):
        temp_path = script_path
        prompts = {
            str(name): str(prompt).strip()
            for name, prompt in script_data["image_prompts"].items()
            if isinstance(name, str) and isinstance(prompt, str)
        }
        prompt_path = None

    # 3. Automatic discovery beside the script.
    if prompts is None:
        prompt_path = discover_prompt_file(script_path)
        if prompt_path is not None:
            prompts = load_prompt_manifest(prompt_path)

    if prompts is None:
        expected = [
            str(script_path.with_name(f"{script_path.stem}_image_prompts.json")),
            str(script_path.with_name("image_prompts.json")),
            str(script_path.parent / "*_image_prompts.json"),
        ]
        raise RuntimeError(
            "Could not find image prompts.\n"
            f"Looked for:\n  - {expected[0]}\n  - {expected[1]}\n"
            f"  - {expected[2]} (only if exactly one matches)\n"
            "or use --prompts PATH."
        )

    # Only generate assets that have prompts. Existing sprites/audio/etc.
    # therefore remain untouched.
    jobs: list[tuple[str, str, Path]] = []

    # Asset paths in the video JSON are project-root-relative.
    # By default, the project root is the current working directory.
    root = args.project_root.resolve()

    for name, prompt in prompts.items():
        if name not in registry:
            print(
                f"Warning: prompt '{name}' is not in asset_registry; skipping.",
                file=sys.stderr,
            )
            continue

        destination = Path(registry[name]["path"])
        if not destination.is_absolute():
            destination = root / destination

        jobs.append((name, prompt, destination))

    if not jobs:
        raise RuntimeError(
            "No prompt entries matched asset_registry. "
            "Check that the prompt 'name' values exactly match asset names."
        )

    print(f"Script:  {script_path}")
    print(
        f"Prompts: {prompt_path if prompt_path is not None else 'embedded in script'}"
    )
    print(f"Root:    {root}")
    print(f"Images:  {len(jobs)}")

    if args.dry_run:
        for name, _, destination in jobs:
            state = "exists" if destination.exists() else "missing"
            print(f"[dry-run] {name}: {destination} ({state})")
        return 0

    # Keep the same key-file convention as the rest of this repository:
    # fal_api_key.txt at the repository root when running from the repo root.
    api_key_path = args.api_key_file
    if not api_key_path.is_absolute():
        api_key_path = Path.cwd() / api_key_path

    api_key = read_api_key(api_key_path).strip()

    generated = 0
    skipped = 0

    for index, (name, prompt, destination) in enumerate(jobs, start=1):
        if destination.exists() and not args.force:
            print(
                f"[{index}/{len(jobs)}] SKIP {name}: "
                f"{destination} already exists"
            )
            skipped += 1
            continue

        destination.parent.mkdir(parents=True, exist_ok=True)

        print(f"[{index}/{len(jobs)}] GENERATE {name}")
        print(f"  -> {destination}")

        generate_image(
            api_key,
            prompt,
            destination,
            width=args.width,
            height=args.height,
        )

        print(f"  saved: {destination}")
        generated += 1

        if args.delay > 0 and index < len(jobs):
            time.sleep(args.delay)

    print(
        f"Done. Generated {generated}, skipped {skipped}, "
        f"total {len(jobs)}."
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1)
