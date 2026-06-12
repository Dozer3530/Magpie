"""Export service: build the weekly package + per-location status.

Moves the orchestration from the Export tab: `_export_crop` (excel + gpkg +
image copy), `_zip_week` (atomic zip bundling), the export-all loop, and the
per-location filled-field status computation (which also feeds the web
Week-overview view).
"""
from __future__ import annotations

import zipfile
from dataclasses import dataclass, field as dc_field
from pathlib import Path

from app.config import EXPORTS_DIR
from app.crops import CROPS, crop_by_code
from app.db import connect, list_locations, list_obs_for_week
from app.exporters.excel_export import export_excel, export_filename as excel_filename
from app.exporters.gpkg_export import export_gpkg, export_filename as gpkg_filename
from app.exporters.images_export import copy_week_images
from app.schema import read_template_fields


# ---- Per-location status ---------------------------------------------------

@dataclass
class LocationStatus:
    location_id: str
    lat: float
    lon: float
    filled: int          # count of non-empty observation fields


@dataclass
class WeekStatus:
    locations: list[LocationStatus]
    locations_with_data: int
    expected_fields: int   # template columns that count as "data" (excl ID/Location/Images)

    @property
    def total_locations(self) -> int:
        return len(self.locations)


def week_status(crop_code: str, iso_week: str) -> WeekStatus:
    """Per-location filled-field counts + coverage for (crop, week).

    Feeds both the desktop Export status view and the Week-overview screen
    (which also uses `expected_fields` to show a completion percentage).
    """
    crop = crop_by_code(crop_code)
    fields = read_template_fields(crop.template_path)
    expected = sum(1 for f in fields if f.name not in ("ID", "Location", "Images"))

    with connect() as conn:
        locs = list_locations(conn, crop_code)
        obs = {r["location_id"]: dict(r) for r in list_obs_for_week(conn, crop_code, iso_week)}

    statuses: list[LocationStatus] = []
    for loc in locs:
        row = obs.get(loc["location_id"], {})
        filled = sum(
            1 for k, v in row.items()
            if k not in ("iso_week", "location_id") and v not in (None, "")
        )
        statuses.append(LocationStatus(
            location_id=loc["location_id"],
            lat=loc["lat"],
            lon=loc["lon"],
            filled=filled,
        ))
    with_data = sum(1 for l in locs if obs.get(l["location_id"]))
    return WeekStatus(
        locations=statuses,
        locations_with_data=with_data,
        expected_fields=expected,
    )


# ---- Package build ---------------------------------------------------------

@dataclass
class ExportResult:
    week: str
    produced: list[Path] = dc_field(default_factory=list)
    errors: list[tuple[str, str]] = dc_field(default_factory=list)  # (crop_code, message)
    zip_path: Path | None = None


def week_dir(iso_week: str) -> Path:
    return EXPORTS_DIR / iso_week


def _export_crop(crop_code: str, iso_week: str, out_dir: Path) -> list[Path]:
    """Write xlsx + gpkg + copy images for one crop. Raises on failure."""
    out_dir.mkdir(parents=True, exist_ok=True)
    xlsx_path = out_dir / excel_filename(crop_code, iso_week)
    gpkg_path = out_dir / gpkg_filename(crop_code, iso_week)
    export_excel(crop_code, iso_week, xlsx_path)
    export_gpkg(crop_code, iso_week, gpkg_path)
    copy_week_images(crop_code, iso_week, out_dir)
    return [xlsx_path, gpkg_path]


def _export_reactive(iso_week: str, out_dir: Path) -> list[Path]:
    """Write Reactive_<Crop> xlsx+gpkg for any crop with reactive points this
    week, into the SAME week folder so they land in the zip. No reactive data
    for a crop → no files (the normal package is unchanged)."""
    from app.exporters.reactive_excel import export_reactive_excel
    from app.exporters.reactive_excel import export_filename as rx_xlsx_name
    from app.exporters.reactive_gpkg import export_reactive_gpkg
    from app.exporters.reactive_gpkg import export_filename as rx_gpkg_name
    from app.services import reactive as reactive_service

    produced: list[Path] = []
    for crop_cfg in CROPS:
        if not reactive_service.has_reactive(crop_cfg.code, iso_week):
            continue
        out_dir.mkdir(parents=True, exist_ok=True)
        xlsx_path = out_dir / rx_xlsx_name(crop_cfg.code, iso_week)
        gpkg_path = out_dir / rx_gpkg_name(crop_cfg.code, iso_week)
        export_reactive_excel(crop_cfg.code, iso_week, xlsx_path)
        export_reactive_gpkg(crop_cfg.code, iso_week, gpkg_path)
        produced += [xlsx_path, gpkg_path]
    return produced


def _zip_week(iso_week: str) -> Path | None:
    """Bundle everything in the week folder into EarthDaily_<week>.zip.

    Atomic: write to a temp name then rename, so a half-zip never leaves a
    confusing file behind.
    """
    wdir = week_dir(iso_week)
    if not wdir.is_dir():
        return None
    zip_path = wdir / f"EarthDaily_{iso_week}.zip"
    tmp_path = zip_path.with_suffix(".zip.tmp")
    try:
        with zipfile.ZipFile(tmp_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for path in sorted(wdir.rglob("*")):
                if path == zip_path or path == tmp_path:
                    continue
                if path.is_file():
                    zf.write(path, path.relative_to(wdir))
        if zip_path.exists():
            zip_path.unlink()
        tmp_path.rename(zip_path)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise
    return zip_path


def _auto_publish_progress() -> None:
    """Best-effort refresh of the shared progress page after an export.

    Publishing must never make an export fail, so this swallows everything; it
    only does anything if the user has configured a publish folder.
    """
    try:
        from app.services import publish
        if publish.get_publish_dir():
            publish.publish_progress()
    except Exception:
        pass


def build_week_package(crop_code: str, iso_week: str) -> ExportResult:
    """Export one crop for a week, then zip the whole week folder."""
    res = ExportResult(week=iso_week)
    out_dir = week_dir(iso_week)
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        res.produced.extend(_export_crop(crop_code, iso_week, out_dir))
    except Exception as exc:
        res.errors.append((crop_code, f"{type(exc).__name__}: {exc}"))
    try:
        res.produced.extend(_export_reactive(iso_week, out_dir))
    except Exception as exc:
        res.errors.append(("reactive", f"{type(exc).__name__}: {exc}"))
    if res.produced:
        res.zip_path = _zip_week(iso_week)
        if res.zip_path:
            res.produced.append(res.zip_path)
    _auto_publish_progress()
    return res


def build_all(iso_week: str) -> ExportResult:
    """Export every crop for a week, then zip the whole week folder.

    Per-crop failures are collected (not raised) so the remaining crops still
    export — matching the desktop tab's behaviour.
    """
    res = ExportResult(week=iso_week)
    out_dir = week_dir(iso_week)
    out_dir.mkdir(parents=True, exist_ok=True)
    for crop_cfg in CROPS:
        try:
            res.produced.extend(_export_crop(crop_cfg.code, iso_week, out_dir))
        except Exception as exc:
            res.errors.append((crop_cfg.code, f"{type(exc).__name__}: {exc}"))
    try:
        res.produced.extend(_export_reactive(iso_week, out_dir))
    except Exception as exc:
        res.errors.append(("reactive", f"{type(exc).__name__}: {exc}"))
    if res.produced:
        res.zip_path = _zip_week(iso_week)
        if res.zip_path:
            res.produced.append(res.zip_path)
    _auto_publish_progress()
    return res
