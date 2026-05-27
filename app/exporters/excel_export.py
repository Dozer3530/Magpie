"""Stamp the weekly observation rows into a copy of the crop template.

The export is a copy of the per-crop `Static <Crop> Template.xlsx` with rows
2..N filled in from the DB. We preserve the template's styling (fonts,
column widths, header formatting) by writing into the loaded workbook and
saving it under the new path; we never re-create the file from scratch.

One row per location, in `locations` table order (M1..M9 / L1..L9). Locations
with no observation for the week get an ID + Location entry and blank cells
everywhere else.
"""
from __future__ import annotations

from pathlib import Path

import openpyxl

from app import image_storage
from app.crops import CropConfig, crop_by_code
from app.db import connect, list_locations, list_obs_for_week
from app.schema import Field, FieldKind, read_template_fields


def _coerce_value(field: Field, raw: str):
    """Convert a stored TEXT value to the right Python type for openpyxl.

    Blank → None (empty cell). NUMBER → float (or int if it round-trips).
    Everything else → str.
    """
    if raw == "" or raw is None:
        return None
    if field.kind == FieldKind.NUMBER:
        try:
            f = float(raw)
            return int(f) if f.is_integer() else f
        except ValueError:
            return raw
    return raw


def _images_formula(crop_code: str, location_id: str, raw: str) -> str | None:
    """Build the HYPERLINK formula for the Images cell.

    - 1 photo → link directly to the file
    - 2+ photos → link to the location's folder so the client sees them all
    """
    names = image_storage.parse_list(raw)
    if not names:
        return None
    rel_base = f"images/{crop_code}/{location_id}/"
    if len(names) == 1:
        # Excel formulas use "" to escape inner quotes; our paths/names don't
        # contain quotes so a plain interpolation is safe.
        return f'=HYPERLINK("{rel_base}{names[0]}","{names[0]}")'
    return f'=HYPERLINK("{rel_base}","{len(names)} photos")'


def export_excel(crop_code: str, iso_week: str, out_path: Path) -> Path:
    """Write `<Crop>_<iso_week>.xlsx` to `out_path`. Returns the written path."""
    crop: CropConfig = crop_by_code(crop_code)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    wb = openpyxl.load_workbook(crop.template_path)
    ws = wb.active

    fields = read_template_fields(crop.template_path)
    col_by_name = {f.name: f.excel_col for f in fields}
    field_by_name = {f.name: f for f in fields}

    with connect() as conn:
        locations = list_locations(conn, crop_code)
        obs_rows = list_obs_for_week(conn, crop_code, iso_week)
    obs_by_loc = {row["location_id"]: dict(row) for row in obs_rows}

    # Clear any pre-existing data rows beyond row 1 in the template (the
    # shipped templates have empty A2..N rows with ID/Location pre-filled —
    # we'll rewrite them all so the template's lat/long is authoritative).
    if ws.max_row >= 2:
        ws.delete_rows(2, ws.max_row - 1)

    for r, loc in enumerate(locations, start=2):
        loc_id = loc["location_id"]
        if "ID" in col_by_name:
            ws.cell(row=r, column=col_by_name["ID"], value=loc_id)
        if "Location" in col_by_name:
            ws.cell(
                row=r,
                column=col_by_name["Location"],
                value=f"{loc['lat']}, {loc['lon']}",
            )
        obs = obs_by_loc.get(loc_id, {})
        for name, col in col_by_name.items():
            if name in ("ID", "Location"):
                continue
            field = field_by_name[name]
            if field.kind == FieldKind.IMAGES:
                formula = _images_formula(crop_code, loc_id, obs.get(name, ""))
                if formula is not None:
                    ws.cell(row=r, column=col, value=formula)
                continue
            value = _coerce_value(field, obs.get(name, ""))
            if value is not None:
                ws.cell(row=r, column=col, value=value)

    wb.save(out_path)
    return out_path


def export_filename(crop_code: str, iso_week: str) -> str:
    crop = crop_by_code(crop_code)
    return f"{crop.display_name}_{iso_week}.xlsx"
