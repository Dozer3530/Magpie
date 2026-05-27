"""On-disk image storage for the app.

Layout:
    data/images/<crop_code>/<iso_week>/<location_id>/<filename>

The DB's `Images` column stores a semicolon-separated list of *filenames only*
(no paths) — the app derives full paths from the (crop, week, location) tuple
plus this storage layout. Keeps the DB portable and makes it trivial to move
all images by moving the folder.

All file operations are tolerant: missing source files are reported, name
collisions get -1/-2 suffixes rather than overwriting.
"""
from __future__ import annotations

import shutil
from pathlib import Path

from app.config import DATA_DIR

IMAGES_ROOT = DATA_DIR / "images"
# Separator the app uses in the DB `Images` column.
LIST_SEP = ";"

# Extensions we treat as image files for filtering.
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".heic", ".heif", ".webp", ".tif", ".tiff", ".bmp"}


def location_dir(crop_code: str, iso_week: str, location_id: str) -> Path:
    """Folder where this (crop, week, location)'s photos live. Created on demand."""
    return IMAGES_ROOT / crop_code / iso_week / location_id


def parse_list(images_cell: str | None) -> list[str]:
    """Parse the DB `Images` value into clean filenames."""
    if not images_cell:
        return []
    return [p.strip() for p in images_cell.split(LIST_SEP) if p.strip()]


def format_list(filenames: list[str]) -> str:
    """Inverse of parse_list — assemble the DB cell value."""
    return f"{LIST_SEP} ".join(filenames)


def _unique_name(folder: Path, name: str) -> str:
    """Return `name` if free; otherwise `name-1.ext`, `name-2.ext`, ..."""
    target = folder / name
    if not target.exists():
        return name
    stem, dot, ext = name.rpartition(".")
    if not dot:
        stem, ext = name, ""
    else:
        ext = "." + ext
    for i in range(1, 1000):
        candidate = f"{stem}-{i}{ext}"
        if not (folder / candidate).exists():
            return candidate
    raise RuntimeError(f"Could not pick a free name for {name} in {folder}")


def attach(
    crop_code: str,
    iso_week: str,
    location_id: str,
    source: Path,
) -> str:
    """Copy `source` into the location's storage. Returns the stored filename.

    The returned filename is what should be appended to the DB `Images` cell.
    """
    source = Path(source)
    if not source.is_file():
        raise FileNotFoundError(f"Image not found: {source}")
    dest_dir = location_dir(crop_code, iso_week, location_id)
    dest_dir.mkdir(parents=True, exist_ok=True)
    final_name = _unique_name(dest_dir, source.name)
    shutil.copy2(source, dest_dir / final_name)
    return final_name


def remove(
    crop_code: str,
    iso_week: str,
    location_id: str,
    filename: str,
) -> bool:
    """Delete one stored photo. Returns True if removed, False if missing."""
    target = location_dir(crop_code, iso_week, location_id) / filename
    if not target.exists():
        return False
    target.unlink()
    return True


def absolute_path(
    crop_code: str,
    iso_week: str,
    location_id: str,
    filename: str,
) -> Path:
    return location_dir(crop_code, iso_week, location_id) / filename


def list_existing(
    crop_code: str,
    iso_week: str,
    location_id: str,
) -> list[str]:
    """Filenames that actually exist on disk for this (crop, week, location)."""
    folder = location_dir(crop_code, iso_week, location_id)
    if not folder.is_dir():
        return []
    return sorted(p.name for p in folder.iterdir() if p.is_file())
