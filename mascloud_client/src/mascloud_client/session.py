"""Local client state — endpoint + bearer token in ~/.mascloud/config.json.

This is the ONLY thing the CLI persists. It never contains a Fireworks or
Daytona key — only the trainer's session token, which authorizes calls to our
API and nothing else.
"""

from __future__ import annotations

import json
import os
from pathlib import Path


def _config_path() -> Path:
    root = Path(os.environ.get("MASCLOUD_HOME", Path.home() / ".mascloud"))
    root.mkdir(parents=True, exist_ok=True)
    return root / "config.json"


def load() -> dict:
    path = _config_path()
    return json.loads(path.read_text()) if path.exists() else {}


def save(config: dict) -> None:
    _config_path().write_text(json.dumps(config, indent=2))


def clear() -> None:
    path = _config_path()
    if path.exists():
        path.unlink()