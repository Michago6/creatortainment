#!/usr/bin/env python3
"""Generate per-scene image and audio assets from a simple scene script."""

from __future__ import annotations

import argparse
import base64
import mimetypes
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests


API_BASE = "https://api.elevenlabs.io/v1"
DEFAULT_IMAGE_MODEL = "gemini-3.1-flash-lite-image"
DEFAULT_TTS_MODEL = "eleven_multilingual_v2"
DEFAULT_OUTPUT_FORMAT = "mp3_44100_128"
DEFAULT_POLL_SECONDS = 2
DEFAULT_TIMEOUT_SECONDS = 900

SCENE_RE = re.compile(
    r"(?ms)^\s*SCENE\s+(\d+)\s*$"
    r"(.*?)(?=^\s*SCENE\s+\d+\s*$|\Z)"
)
VISUAL_RE = re.compile(r"(?ms)^\s*\[VISUAL\]\s*(.*?)(?=^\s*\[SPEAK\])")
SPEAK_RE = re.compile(r"(?ms)^\s*\[SPEAK\]\s*(.*)\s*$")


@dataclass(frozen=True)
class Scene:
    number: int
    visual: str
    speak: str


class ApiError(RuntimeError):
    """Raised when ElevenLabs returns an unsuccessful or unusable response."""


def parse_script(text: str) -> list[Scene]:
    scenes: list[Scene] = []
    for match in SCENE_RE.finditer(text):
        number = int(match.group(1))
        body = match.group(2).strip()
        visual_match = VISUAL_RE.search(body)
        speak_match = SPEAK_RE.search(body)
        if not visual_match or not speak_match:
            raise ValueError(
                f"Scene {number} must contain both [VISUAL] and [SPEAK] sections."
            )
        visual = " ".join(visual_match.group(1).split())
        speak = " ".join(speak_match.group(1).split())
        if not visual or not speak:
            raise ValueError(f"Scene {number} has an empty visual or speak section.")
        scenes.append(Scene(number=number, visual=visual, speak=speak))

    if not scenes:
        raise ValueError("No scenes found. Scenes must start with a line like: SCENE 1")
    expected = list(range(1, len(scenes) + 1))
    actual = [scene.number for scene in scenes]
    if actual != expected:
        raise ValueError(
            f"Scene numbers must be consecutive starting at 1; found {actual}."
        )
    return scenes


def read_api_key(path: Path) -> str:
    if not path.exists():
        raise FileNotFoundError(
            f"Missing {path}. Create it with one ElevenLabs API key on the first non-empty line."
        )
    for line in path.read_text(encoding="utf-8").splitlines():
        key = line.strip()
        if key and not key.startswith("#"):
            return key
    raise ValueError(f"{path} does not contain a non-empty API key.")


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip()).strip("-").lower()
    return slug or "project"


def write_text(path: Path, content: str) -> None:
    path.write_text(content.rstrip() + "\n", encoding="utf-8")


def reference_payload(paths: list[Path]) -> list[dict[str, str]]:
    references = []
    for path in paths:
        if not path.is_file():
            raise FileNotFoundError(f"Reference image not found: {path}")
        mime_type, _ = mimetypes.guess_type(path.name)
        if mime_type not in {"image/jpeg", "image/png", "image/webp", "image/heic", "image/heif"}:
            raise ValueError(
                f"Unsupported reference image type for {path}. Use JPEG, PNG, WEBP, HEIC, or HEIF."
            )
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        references.append(
            {
                "type": "inline_base64",
                "content_base64": encoded,
                "mime_type": mime_type,
            }
        )
    return references


class ElevenLabsClient:
    def __init__(self, api_key: str, timeout: int = 60) -> None:
        self.session = requests.Session()
        self.session.headers.update(
            {"xi-api-key": api_key, "Accept": "application/json"}
        )
        self.timeout = timeout

    def _json(self, response: requests.Response) -> dict[str, Any]:
        if not response.ok:
            detail = response.text.strip()
            raise ApiError(
                f"ElevenLabs request failed ({response.status_code}): {detail[:500]}"
            )
        try:
            data = response.json()
        except ValueError as exc:
            raise ApiError("ElevenLabs returned invalid JSON.") from exc
        if not isinstance(data, dict):
            raise ApiError("ElevenLabs returned an unexpected response.")
        return data

    def generate_image(
        self,
        prompt: str,
        model: str,
        references: list[dict[str, str]],
        poll_seconds: int,
        timeout_seconds: int,
    ) -> bytes:
        body: dict[str, Any] = {
            "model_id": model,
            "prompt": prompt,
            "aspect_ratio": "9:16",
            "resolution": "1K",
        }
        if references:
            body["images"] = references
        response = self.session.post(
            f"{API_BASE}/flows/image", json=body, timeout=self.timeout
        )
        generation = self._json(response)
        generation_id = generation.get("id")
        if not isinstance(generation_id, str) or not generation_id:
            raise ApiError("Image generation response did not include an id.")
        result = self._poll_generation(
            f"{API_BASE}/flows/image/{generation_id}",
            poll_seconds,
            timeout_seconds,
        )
        content_url = result.get("content_url")
        if not isinstance(content_url, str) or not content_url:
            raise ApiError("Completed image response did not include content_url.")
        download = self.session.get(content_url, timeout=self.timeout)
        if not download.ok:
            raise ApiError(
                f"Could not download generated image ({download.status_code})."
            )
        return download.content

    def _poll_generation(
        self, url: str, poll_seconds: int, timeout_seconds: int
    ) -> dict[str, Any]:
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            response = self.session.get(url, timeout=self.timeout)
            result = self._json(response)
            status = result.get("status")
            if status == "completed":
                return result
            if status == "failed":
                reason = result.get("failure_reason") or result.get("error_message")
                raise ApiError(f"Generation failed: {reason or 'unknown error'}")
            time.sleep(poll_seconds)
        raise TimeoutError(f"Generation did not finish within {timeout_seconds} seconds.")

    def generate_audio(
        self, text: str, voice_id: str, model: str, output_format: str
    ) -> bytes:
        response = self.session.post(
            f"{API_BASE}/text-to-speech/{voice_id}",
            params={"output_format": output_format},
            json={"text": text, "model_id": model},
            headers={"Accept": "audio/mpeg"},
            timeout=self.timeout,
        )
        if not response.ok:
            detail = response.text.strip()
            raise ApiError(
                f"ElevenLabs TTS failed ({response.status_code}): {detail[:500]}"
            )
        return response.content


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create scene text, image, and ElevenLabs TTS assets from a script."
    )
    parser.add_argument("script", type=Path, help="Path to the scene script text file.")
    parser.add_argument(
        "--name", required=True, help="Project name used for the output folder."
    )
    parser.add_argument(
        "--voice-id",
        help="ElevenLabs voice ID used for every scene's narration.",
    )
    parser.add_argument(
        "--reference",
        action="append",
        type=Path,
        default=[],
        help="Reference image path. Repeat for additional reference images.",
    )
    parser.add_argument(
        "--api-key-file",
        type=Path,
        default=Path("api_key.txt"),
        help="API key file (default: api_key.txt).",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("projects"),
        help="Parent directory for project folders (default: projects).",
    )
    parser.add_argument(
        "--image-model",
        default=DEFAULT_IMAGE_MODEL,
        help=f"ElevenLabs image model (default: {DEFAULT_IMAGE_MODEL}).",
    )
    parser.add_argument(
        "--tts-model",
        default=DEFAULT_TTS_MODEL,
        help=f"ElevenLabs TTS model (default: {DEFAULT_TTS_MODEL}).",
    )
    parser.add_argument(
        "--skip-images",
        action="store_true",
        help="Only create text and audio files; do not call image generation.",
    )
    parser.add_argument(
        "--skip-audio",
        action="store_true",
        help="Only create text and image files; do not call TTS.",
    )
    parser.add_argument(
        "--poll-seconds",
        type=int,
        default=DEFAULT_POLL_SECONDS,
        help="Seconds between image generation status checks.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.poll_seconds < 2:
        raise ValueError("--poll-seconds must be at least 2 for the image API.")
    source_script = args.script.read_bytes()
    script_text = source_script.decode("utf-8")
    scenes = parse_script(script_text)

    project_dir = args.output_dir / slugify(args.name)
    scenes_dir = project_dir / "scenes"
    audio_dir = project_dir / "audio"
    for directory in (scenes_dir, audio_dir):
        directory.mkdir(parents=True, exist_ok=True)

    (project_dir / "script.txt").write_bytes(source_script)
    write_text(project_dir / "script_visual_only.txt", "\n\n".join(scene.visual for scene in scenes))
    write_text(project_dir / "script_speak_only.txt", "\n\n".join(scene.speak for scene in scenes))

    if args.skip_images and args.skip_audio:
        print(f"Created parsed scene files in {project_dir}")
        return 0

    if not args.skip_audio and not args.voice_id:
        raise ValueError("--voice-id is required unless --skip-audio is used.")
    client = ElevenLabsClient(read_api_key(args.api_key_file))
    references = reference_payload(args.reference) if not args.skip_images else []

    for index, scene in enumerate(scenes, start=1):
        prefix = f"[{index}/{len(scenes)}] Scene {scene.number}"
        if not args.skip_images:
            print(f"{prefix}: generating image...", flush=True)
            image_prompt = (
                "Create a 9:16 vertical image. Follow the visual direction exactly. "
                "Preserve the referenced character's identity, proportions, colors, "
                "features, and specified pose. Do not add text unless the visual direction "
                f"explicitly requests it.\n\n{scene.visual}"
            )
            image = client.generate_image(
                image_prompt,
                args.image_model,
                references,
                args.poll_seconds,
                DEFAULT_TIMEOUT_SECONDS,
            )
            (scenes_dir / f"scene_{scene.number:02d}.png").write_bytes(image)

        if not args.skip_audio:
            print(f"{prefix}: generating audio...", flush=True)
            audio = client.generate_audio(
                scene.speak, args.voice_id, args.tts_model, DEFAULT_OUTPUT_FORMAT
            )
            (audio_dir / f"scene_{scene.number:02d}.mp3").write_bytes(audio)

    print(f"Created project assets in {project_dir}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ApiError, OSError, TimeoutError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1)
