"""Tiny JSON-backed key/value store for UI preferences (last-used folder, etc.)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.config import DATA_DIR, ensure_app_dirs

_SETTINGS_PATH = DATA_DIR / "app_settings.json"


def _read() -> dict[str, Any]:
    if not _SETTINGS_PATH.exists():
        return {}
    try:
        return json.loads(_SETTINGS_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _write(data: dict[str, Any]) -> None:
    ensure_app_dirs()
    _SETTINGS_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")


def get(key: str, default: Any = None) -> Any:
    return _read().get(key, default)


def set_(key: str, value: Any) -> None:
    data = _read()
    data[key] = value
    _write(data)
