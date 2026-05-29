"""Frontend parity test — desktop and web produce identical exports.

Both frontends are thin shells over `app/services`. This test seeds one set
of observations, then builds the same week TWO ways:

  * directly through the service layer (the path the PySide6 desktop takes), and
  * through the FastAPI `/api/export` route (the path the browser takes),

and asserts the produced Excel and GeoPackage files are content-identical.

We compare *structured content* (every cell / every feature attribute) rather
than raw bytes: xlsx and gpkg both embed run-timestamps that differ between
two builds, but the data they carry must match exactly for the no-drift
guarantee to hold. The shared `app/services/exports.py` is the single brain;
this proves neither frontend has snuck logic of its own around it.
"""
from __future__ import annotations

import geopandas as gpd
import openpyxl
import pandas as pd

from app.exporters.excel_export import export_filename as xlsx_filename
from app.exporters.gpkg_export import export_filename as gpkg_filename
from app.schema import read_template_fields
from app.services import exports as exports_service
from app.services import observations as obs_service
from tests.conftest import seed_week


def _field_name(fields, key):
    for f in fields:
        if f.key == key:
            return f.name
    raise KeyError(key)


def _sheet_matrix(xlsx_path):
    """Every cell value as a plain nested list (None for blanks)."""
    wb = openpyxl.load_workbook(xlsx_path)
    ws = wb.active
    rows = [[c.value for c in row] for row in ws.iter_rows()]
    wb.close()
    return rows


def _gpkg_frame(gpkg_path):
    """GeoPackage as a stable DataFrame: attributes + geometry-as-WKT."""
    gdf = gpd.read_file(gpkg_path).sort_values("ID").reset_index(drop=True)
    gdf["__wkt"] = gdf.geometry.apply(lambda g: g.wkt)
    return gdf.drop(columns="geometry")


def test_desktop_and_web_exports_match(isolated_db, canola, monkeypatch):
    week = seed_week()
    fields = read_template_fields(canola.template_path)
    n_name = _field_name(fields, "N")

    # One set of inputs, saved through the shared observation service.
    obs_service.save("canola", week, "M1", {n_name: "3.2", "Disease_Blackleg": "yes"})
    obs_service.save("canola", week, "M5", {n_name: "1.8"})

    # --- Desktop path: call the export service directly, into dir A ---
    desktop_dir = isolated_db / "exports_desktop"
    monkeypatch.setattr(exports_service, "EXPORTS_DIR", desktop_dir)
    exports_service.build_week_package("canola", week)
    desktop_xlsx = desktop_dir / week / xlsx_filename("canola", week)
    desktop_gpkg = desktop_dir / week / gpkg_filename("canola", week)

    # --- Web path: drive the FastAPI route, into dir B ---
    web_dir = isolated_db / "exports_web"
    monkeypatch.setattr(exports_service, "EXPORTS_DIR", web_dir)
    from fastapi.testclient import TestClient
    from webapp.server import app

    with TestClient(app) as c:
        res = c.post("/api/export", params={"crop": "canola", "week": week}).json()
    web_xlsx = web_dir / week / xlsx_filename("canola", week)
    web_gpkg = web_dir / week / gpkg_filename("canola", week)

    assert res["zip_name"] == f"EarthDaily_{week}.zip"
    assert not res["errors"]

    # Same Excel content, cell-for-cell.
    assert _sheet_matrix(desktop_xlsx) == _sheet_matrix(web_xlsx)

    # Same GeoPackage geometry + attribute table (NaN-safe via pandas).
    pd.testing.assert_frame_equal(_gpkg_frame(desktop_gpkg), _gpkg_frame(web_gpkg))
