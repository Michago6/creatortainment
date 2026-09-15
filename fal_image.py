#!/usr/bin/env python3
"""Generate an image with fal.ai's lowest-cost image model."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


MODEL_ID = "fal-ai/sana"
API_URL = f"https://fal.run/{MODEL_ID}"
DEFAULT_API_KEY_FILE = Path(__file__).with_name("fal_api_key.txt")


def request_json(url: str, *, headers: dict[str, str], body: bytes | None = None) -> dict:
    request = Request(url, data=body, headers=headers, method="POST" if body else "GET")
    try:
        with urlopen(request, timeout=300) as response:
            payload = json.loads(response.read())
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"fal.ai request failed ({exc.code}): {detail[:500]}") from exc
    except URLError as exc:
        raise RuntimeError(f"Could not connect to fal.ai: {exc.reason}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError("fal.ai returned invalid JSON.") from exc

    if not isinstance(payload, dict):
        raise RuntimeError("fal.ai returned an unexpected response.")
    return payload


def generate_image(api_key: str, prompt: str, output_path: Path) -> None:
    body = json.dumps({"prompt": prompt}).encode("utf-8")
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
        raise RuntimeError("fal.ai response did not contain a generated image.")
    image_url = images[0].get("url") if isinstance(images[0], dict) else None
    if not isinstance(image_url, str) or not image_url:
        raise RuntimeError("fal.ai response did not contain a usable image URL.")

    try:
        with urlopen(Request(image_url), timeout=300) as response:
            output_path.write_bytes(response.read())
    except HTTPError as exc:
        raise RuntimeError(f"Could not download the generated image ({exc.code}).") from exc
    except URLError as exc:
        raise RuntimeError(f"Could not download the generated image: {exc.reason}") from exc


def read_api_key(path: Path) -> str:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise RuntimeError(f"Could not read API key file {path}: {exc}") from exc

    for line in lines:
        key = line.strip()
        if key and not key.startswith("#"):
            return key
    raise RuntimeError(f"API key file {path} is empty.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate an image with fal.ai's lowest-cost image model."
    )
    parser.add_argument(
        "--api-key-file",
        type=Path,
        default=DEFAULT_API_KEY_FILE,
        help=f"API key file (default: {DEFAULT_API_KEY_FILE.name}).",
    )
    parser.add_argument(
        "--prompt",
        help="Image prompt. If omitted, prompt for it interactively.",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=Path("generated.png"),
        help="Output image path (default: generated.png).",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    api_key = read_api_key(args.api_key_file)
    prompt = args.prompt or input("Image prompt: ").strip()

    if not prompt:
        raise ValueError("A prompt is required.")

    generate_image(api_key.strip(), prompt, args.output)
    print(f"Saved image to {args.output}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1)
