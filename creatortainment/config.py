"""Repository-local configuration and credential loading."""

from __future__ import annotations

import os
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = REPO_ROOT / ".env"


def _parse_env_file(path: Path) -> dict[str, str]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return {}
    except OSError as exc:
        raise RuntimeError(f"Could not read configuration file {path}: {exc}") from exc

    values: dict[str, str] = {}
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        name, value = stripped.split("=", 1)
        name = name.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        values[name] = value
    return values


def get_credential(name: str) -> str:
    """Return a credential from the environment or repository ``.env`` file."""
    value = os.environ.get(name)
    if value is None:
        value = _parse_env_file(ENV_PATH).get(name)
    if value is None or not value.strip():
        raise RuntimeError(
            f"Missing required credential {name}. "
            f"Set {name} in {ENV_PATH} or the environment."
        )
    return value.strip()


def get_fal_key() -> str:
    return get_credential("FAL_KEY")


def get_elevenlabs_api_key() -> str:
    return get_credential("ELEVENLABS_API_KEY")
