"""Import service: prepare a file, then commit Survey123 or lab rows.

Moves the orchestration that used to live in the two import tabs:
  - photo-index scanning + the Survey123 loop (location validation,
    project_row, Images attach/format, save, counts)
  - the lab duplicate-target validation + loop

The tabs keep only widget code (file dialog, preview table, dropdowns,
message boxes).
"""
from __future__ import annotations

from dataclasses import dataclass, field as dc_field
from pathlib import Path

from app import image_storage
from app.crops import crop_by_code
from app.db import connect, list_locations, save_obs_row
from app.importers.core import LoadedFile, load_for_crop, project_row


@dataclass
class ImportResult:
    imported: int = 0
    skipped_no_loc: int = 0        # survey: source ID didn't match a location
    skipped_no_target: int = 0     # lab: row left unassigned / (skip)
    skipped_empty: int = 0         # no mapped non-empty values
    photos_copied: int = 0
    photos_missing: int = 0
    warnings: list[str] = dc_field(default_factory=list)


class DuplicateTargetError(Exception):
    """Two lab rows were assigned to the same location in one import."""

    def __init__(self, location_id: str, first_row: int, second_row: int) -> None:
        self.location_id = location_id
        self.first_row = first_row
        self.second_row = second_row
        super().__init__(
            f"Location {location_id} is assigned to both row {first_row + 1} "
            f"and row {second_row + 1}. Each location can receive at most one "
            f"row per import."
        )


def prepare(path: Path, crop_code: str) -> LoadedFile:
    """Load a source file + auto-map its columns against the crop template."""
    crop = crop_by_code(crop_code)
    return load_for_crop(path, crop.template_path)


def valid_locations(crop_code: str) -> set[str]:
    with connect() as conn:
        return {r["location_id"] for r in list_locations(conn, crop_code)}


def find_photo_index(source_file: Path) -> dict[str, Path]:
    """Index image files within 1 level of the source file, keyed by filename.

    Survey123 exports drop photos either alongside the CSV or in a single
    sibling subfolder (commonly `media/`). We handle both.
    """
    source_file = Path(source_file)
    parent = source_file.parent
    if not parent.is_dir():
        return {}
    index: dict[str, Path] = {}
    for p in parent.iterdir():
        if p.is_file() and p.suffix.lower() in image_storage.IMAGE_EXTS:
            index.setdefault(p.name, p)
    for sub in parent.iterdir():
        if not sub.is_dir():
            continue
        for p in sub.iterdir():
            if p.is_file() and p.suffix.lower() in image_storage.IMAGE_EXTS:
                index.setdefault(p.name, p)
    return index


def commit_survey(
    loaded: LoadedFile,
    crop_code: str,
    iso_week: str,
    id_col: str,
) -> ImportResult:
    """Import a Survey123 file: join each row to a location via `id_col`.

    Copies referenced photos into image storage and rewrites the Images cell
    with the stored filenames.
    """
    valids = valid_locations(crop_code)
    photo_index = find_photo_index(loaded.path)
    res = ImportResult()

    with connect() as conn:
        for row in loaded.rows:
            loc_id = row.get(id_col, "").strip()
            if loc_id not in valids:
                res.skipped_no_loc += 1
                continue
            values = project_row(row, loaded.mapping)
            if not values:
                res.skipped_empty += 1
                continue
            if "Images" in values:
                referenced = image_storage.parse_list(values["Images"])
                stored_names: list[str] = []
                for name in referenced:
                    src = photo_index.get(name)
                    if src is None:
                        res.photos_missing += 1
                        stored_names.append(name)
                        continue
                    try:
                        stored = image_storage.attach(crop_code, iso_week, loc_id, src)
                        stored_names.append(stored)
                        res.photos_copied += 1
                    except Exception:
                        res.photos_missing += 1
                        stored_names.append(name)
                values["Images"] = image_storage.format_list(stored_names)
            save_obs_row(conn, crop_code, iso_week, loc_id, values)
            res.imported += 1
    return res


def commit_lab(
    loaded: LoadedFile,
    crop_code: str,
    iso_week: str,
    row_targets: dict[int, str],
) -> ImportResult:
    """Import a lab file using a per-row target-location assignment.

    `row_targets` maps source-row index → location_id. Rows not present in the
    mapping (or mapped to "") are skipped. Raises `DuplicateTargetError` if two
    rows target the same location.
    """
    # Validate one-to-one before writing anything.
    seen: dict[str, int] = {}
    assigned: dict[int, str] = {}
    for r in sorted(row_targets):
        loc = row_targets[r]
        if not loc:
            continue
        if loc in seen:
            raise DuplicateTargetError(loc, seen[loc], r)
        seen[loc] = r
        assigned[r] = loc

    res = ImportResult()
    res.skipped_no_target = loaded.row_count - len(assigned)

    with connect() as conn:
        for r, loc_id in assigned.items():
            row = loaded.rows[r]
            values = project_row(row, loaded.mapping)
            if not values:
                res.skipped_empty += 1
                res.skipped_no_target += 0  # already counted only unassigned
                continue
            save_obs_row(conn, crop_code, iso_week, loc_id, values)
            res.imported += 1
    return res
