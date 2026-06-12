"""GeoPackage export for a week's reactive points (one Point per point).

Parallels `gpkg_export.py`; geometry + attributes come from `reactive_obs` via
`reactive.week_points`. Layer name `reactive_<crop>`. CRS EPSG:4326.
"""
from __future__ import annotations

from pathlib import Path

import geopandas as gpd
from shapely.geometry import Point

from app.crops import crop_by_code
from app.exporters.gpkg_export import _coerce_value
from app.schema import read_template_fields
from app.services import reactive as reactive_service

_DIRECT = ("ID", "Field", "Location")


def export_reactive_gpkg(crop_code: str, iso_week: str, out_path: Path) -> Path:
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    template = reactive_service.reactive_template_path(crop_code)
    fields = read_template_fields(template)
    ordered_names = [f.name for f in fields]
    points = reactive_service.week_points(crop_code, iso_week)

    records: list[dict] = []
    geoms: list[Point] = []
    for pt in points:
        rec: dict = {}
        for f in fields:
            if f.name == "ID":
                rec[f.name] = pt["point_id"]
            elif f.name == "Field":
                rec[f.name] = pt["field"]
            elif f.name == "Location":
                rec[f.name] = f"{pt['lat']}, {pt['lon']}"
            else:
                rec[f.name] = _coerce_value(f, pt["values"].get(f.name, ""))
        records.append(rec)
        geoms.append(Point(float(pt["lon"]), float(pt["lat"])))

    gdf = gpd.GeoDataFrame(records, geometry=geoms, crs="EPSG:4326")
    gdf = gdf[ordered_names + ["geometry"]]
    if out_path.exists():
        out_path.unlink()
    gdf.to_file(out_path, driver="GPKG", layer=f"reactive_{crop_code}")
    return out_path


def export_filename(crop_code: str, iso_week: str) -> str:
    return f"Reactive_{crop_by_code(crop_code).display_name}_{iso_week}.gpkg"
