"""Service-layer characterization — the public API both frontends call.

These pin the orchestration that moved out of the Qt tabs: week CRUD, the
form-schema structure, the two import paths, and the export package + status.
"""
from __future__ import annotations

import geopandas as gpd
import openpyxl
import pytest

from app import db
from app.importers.core import load_for_crop
from app.services import exports, imports, observations, weeks
from tests.conftest import seed_week


# ---- weeks ----------------------------------------------------------------

def test_current_iso_week_format():
    tag = weeks.current_iso_week()
    assert len(tag) == 8 and tag[4:6] == "-W"


def test_ensure_current_week_then_idempotent(isolated_db):
    created = weeks.ensure_current_week()
    assert created == weeks.current_iso_week()
    # Second call is a no-op because a week now exists.
    assert weeks.ensure_current_week() is None
    assert weeks.current_iso_week() in weeks.list_week_tags()


def test_create_and_delete_week(isolated_db):
    weeks.create_week("2026-W30")
    assert "2026-W30" in weeks.list_week_tags()
    weeks.delete_week("2026-W30")
    assert "2026-W30" not in weeks.list_week_tags()


# ---- form schema ----------------------------------------------------------

def test_build_form_schema_structure(isolated_db):
    schema = observations.build_form_schema("canola")
    titles = [(s.page, s.title, s.kind) for s in schema.sections]

    assert titles == [
        ("field", "Observation header", "form"),
        ("field", "Soil readings (TDR)", "tdr_grid"),
        ("field", "Diseases", "disease_table"),
        ("field", "Insects", "form"),
        ("field", "Petal test", "form"),
        ("field", "Photos", "images"),
        ("lab", "Report identifiers", "form"),
        ("lab", "Nutrient panel", "nutrient_table"),
        ("lab", "Nutrient ratios", "ratio_table"),
    ]

    by_title = {s.title: s for s in schema.sections}
    # Domain counts carried through the schema.
    assert len(by_title["Diseases"].disease_rows) == 8
    assert len(by_title["Nutrient panel"].nutrient_rows) == 16
    assert len(by_title["Nutrient ratios"].ratio_rows) == 8
    assert len(by_title["Soil readings (TDR)"].tdr_rows) == 3
    # TDR row resolves the unit-bearing header for each reading.
    tdr1 = by_title["Soil readings (TDR)"].tdr_rows[0]
    assert tdr1.temperature.name == "TDR_1_SOIL_TEMPERATURE (°C)"


def test_observation_load_save(isolated_db):
    week = seed_week()
    observations.save("canola", week, "M1", {"Disease_Blackleg": "yes"})
    loaded = observations.load("canola", week, "M1")
    assert loaded["Disease_Blackleg"] == "yes"


# ---- imports --------------------------------------------------------------

def _survey_csv(tmp_path, canola):
    csv = tmp_path / "survey.csv"
    csv.write_text(
        "ID,Date_Time,N,Disease_Blackleg\n"
        "M1,2026-05-28,3.2,yes\n"
        "M2,2026-05-28,2.9,\n"
        "ZZ,2026-05-28,1.0,yes\n",  # unknown location -> skipped_no_loc
        encoding="utf-8",
    )
    return csv


def test_commit_survey_counts(isolated_db, tmp_path, canola):
    week = seed_week()
    csv = _survey_csv(tmp_path, canola)
    loaded = imports.prepare(csv, "canola")
    res = imports.commit_survey(loaded, "canola", week, "ID")

    assert res.imported == 2          # M1, M2
    assert res.skipped_no_loc == 1    # ZZ
    assert observations.load("canola", week, "M1")["N (%)"] == "3.2"


def test_commit_lab_duplicate_target_raises(isolated_db, tmp_path, canola):
    week = seed_week()
    csv = tmp_path / "lab.csv"
    csv.write_text("SampleID,N\nA,3.0\nB,2.0\n", encoding="utf-8")
    loaded = imports.prepare(csv, "canola")

    with pytest.raises(imports.DuplicateTargetError):
        imports.commit_lab(loaded, "canola", week, {0: "M1", 1: "M1"})


def test_commit_lab_assigns(isolated_db, tmp_path, canola):
    week = seed_week()
    csv = tmp_path / "lab.csv"
    csv.write_text("SampleID,N\nA,3.0\nB,2.0\n", encoding="utf-8")
    loaded = imports.prepare(csv, "canola")

    res = imports.commit_lab(loaded, "canola", week, {0: "M1", 1: "M2"})
    assert res.imported == 2
    assert observations.load("canola", week, "M1")["N (%)"] == "3.0"


# ---- exports --------------------------------------------------------------

def test_week_status(isolated_db):
    week = seed_week()
    observations.save("canola", week, "M1", {"Disease_Blackleg": "yes", "ReportNo": "x"})
    status = observations  # noqa: F841 (placeholder to keep import warnings quiet)
    ws = exports.week_status("canola", week)

    assert ws.total_locations == 9
    assert ws.locations_with_data == 1
    m1 = next(l for l in ws.locations if l.location_id == "M1")
    assert m1.filled == 2


def test_build_week_package(isolated_db, monkeypatch):
    # Redirect exports into tmp so we don't touch the real exports/ folder.
    monkeypatch.setattr(exports, "EXPORTS_DIR", isolated_db / "exports")
    week = seed_week()
    observations.save("canola", week, "M1", {"Disease_Blackleg": "yes"})

    res = exports.build_week_package("canola", week)
    assert not res.errors
    assert res.zip_path is not None and res.zip_path.is_file()
    names = {p.name for p in res.produced}
    assert f"Canola_{week}.xlsx" in names
    assert f"Canola_{week}.gpkg" in names

    # The produced files are real + well-formed.
    wb_path = res.zip_path.parent / f"Canola_{week}.xlsx"
    wb = openpyxl.load_workbook(wb_path)
    assert wb.active.cell(row=1, column=1).value == "ID"
    wb.close()
    gdf = gpd.read_file(res.zip_path.parent / f"Canola_{week}.gpkg")
    assert len(gdf) == 9


def test_build_all_two_crops(isolated_db, monkeypatch):
    monkeypatch.setattr(exports, "EXPORTS_DIR", isolated_db / "exports")
    week = seed_week()
    res = exports.build_all(week)
    assert not res.errors
    names = {p.name for p in res.produced}
    assert f"Canola_{week}.xlsx" in names
    assert f"Corn_{week}.xlsx" in names
    assert res.zip_path is not None and res.zip_path.is_file()
