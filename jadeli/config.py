"""Portable app configuration (kept next to the app, not in the registry)."""

from __future__ import annotations

import json
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = APP_DIR / "config.json"
WEB_DIR = APP_DIR / "web"
DEFAULT_VAULT = APP_DIR / "vault"
DEFAULT_LIBRARY = APP_DIR / "library"

VERSION = "1.0.0"

DEFAULTS = {
    "vault": str(DEFAULT_VAULT),
    "library": [str(DEFAULT_LIBRARY)],
    "legacy_jadeli": "D:\\Personal\\jadeli",
    "convert_engine": "auto",
    "theme": "dark",
    "view_mode": "split",
    "last_note": "",
    "sidebar_tab": "files",
    "right_panel": "outline",
}


def load_config() -> dict:
    config = dict(DEFAULTS)
    if CONFIG_PATH.exists():
        try:
            stored = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            stored = {}
        if isinstance(stored, dict):
            config.update({key: value for key, value in stored.items() if value is not None})
    return config


def save_config(config: dict) -> None:
    payload = {key: config.get(key, value) for key, value in DEFAULTS.items()}
    try:
        CONFIG_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    except OSError:
        pass
