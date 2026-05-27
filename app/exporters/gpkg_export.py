"""GeoPackage export: one Point feature per location, attributes = template columns.

The point geometry comes from the `locations` table (lat/lon stored at seed
time from the template's column B). CRS is EPSG:4326 (WGS84) — that's what
the source "lat, lon" strings in the templates are.

Column names with special characters (e.g. `N/S_Actual`, `Petal_Test_Total_Infected_%`)
do round-trip through GeoPackage but some GIS clients may quote them in
display. Worth noting if the client opens these in older tools.
"""
from __future__ import annotations

from pathlib import Path

import geopandas as gpd
from shapely.geometry import Point

from app.crops import CropConfig, crop_by_code
from app.db import connect, list_locations, list_obs_for_week
from app.schema import Field, FieldKind, read_template_fields


def _coerce_value(field: Field, raw: str):
    """Same coercion as the Excel export — numeric where it makes sense."""
    if raw == "" or raw is None:
        return None
    if field.kind == FieldKind.NUMBER:
        try:
            return float(raw)
        except ValueError:
            return raw
    return raw


def export_gpkg(crop_code: str, iso_week: str, out_path: Path) -> Path:
    crop: CropConfig = crop_by_code(crop_code)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    fields = read_template_fields(crop.template_path)
    # Column order mirrors the template so a GPKG reader sees the same shape.
    ordered_names = [f.name for f in fields]

    with connect() as conn:
        locations = list_locations(conn, crop_code)
        obs_rows = list_obs_for_week(conn, crop_code, iso_week)
    obs_by_loc = {row["location_id"]: dict(row) for row in obs_rows}

    records: list[dict] = []
    points: list[Point] = []
    for loc in locations:
        loc_id = loc["location_id"]
        obs = obs_by_loc.get(loc_id, {})
        rec: dict = {}
        for f in fields:
            if f.name == "ID":
                rec[f.name] = loc_id
            elif f.name == "Location":
                rec[f.name] = f"{loc['lat']}, {loc['lon']}"
            else:
                rec[f.name] = _coerce_value(f, obs.get(f.name, ""))
        records.append(rec)
        points.append(Point(float(loc["lon"]), float(loc["lat"])))

    gdf = gpd.GeoDataFrame(records, geometry=points, crs="EPSG:4326")
    # Preserve the template's column order even though pandas will reorder
    # alphabetically by default for some operations.
    gdf = gdf[ordered_names + ["geometry"]]

    # Overwrite any existing layer of this name; one GPKG per crop per week
    # so we don't have to worry about mixing layers.
    if out_path.exists():
        out_path.unlink()
    gdf.to_file(out_path, driver="GPKG", layer=crop.code)
    return out_path


def export_filename(crop_code: str, iso_week: str) -> str:
    crop = crop_by_code(crop_code)
    return f"{crop.display_name}_{iso_week}.gpkg"
