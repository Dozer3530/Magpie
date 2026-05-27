"""Filesystem paths and app-wide constants."""
from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
EXPORTS_DIR = PROJECT_ROOT / "exports"
ASSETS_DIR = PROJECT_ROOT / "assets"
DB_PATH = DATA_DIR / "packages.sqlite"
LAB_PROFILES_PATH = DATA_DIR / "lab_mapping_profiles.json"
LOGO_PATH = ASSETS_DIR / "logo.png"


def ensure_app_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
