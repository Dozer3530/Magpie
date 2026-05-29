"""Importer characterization: load + auto-map + project_row.

Pins the unit-stripped mapping (a lab column "N" must target the template's
"N (%)" header) and the blank-dropping / never-write behavior of project_row.
"""
from __future__ import annotations

from app.importers.core import (
    auto_map_columns,
    load_for_crop,
    project_row,
)
from app.schema import read_template_fields


def _write_csv(path, header, *rows):
    lines = [",".join(header)] + [",".join(r) for r in rows]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_auto_map_unit_stripped(canola):
    fields = read_template_fields(canola.template_path)
    mapping = auto_map_columns(["ID", "Date_Time", "N", "Disease_Blackleg"], fields)

    # "N" maps to the unit-bearing template header.
    assert mapping.matches["N"] == "N (%)"
    assert mapping.matches["Date_Time"] == "Date_Time"
    assert mapping.matches["Disease_Blackleg"] == "Disease_Blackleg"
    assert mapping.matches["ID"] == "ID"


def test_auto_map_reports_unmatched(canola):
    fields = read_template_fields(canola.template_path)
    mapping = auto_map_columns(["ID", "TotallyMadeUpColumn"], fields)
    assert "TotallyMadeUpColumn" in mapping.unmatched_source
    assert "TotallyMadeUpColumn" not in mapping.matches


def test_project_row_drops_blanks_and_pk(canola):
    fields = read_template_fields(canola.template_path)
    mapping = auto_map_columns(["ID", "N", "Disease_Blackleg"], fields)
    row = {"ID": "M1", "N": "3.2", "Disease_Blackleg": ""}

    projected = project_row(row, mapping)

    # ID is never written (PK / locations own it); blank Disease dropped.
    assert "ID" not in projected
    assert "Disease_Blackleg" not in projected
    # N value is kept under the template's unit-bearing column name.
    assert projected["N (%)"] == "3.2"


def test_load_for_crop_end_to_end(tmp_path, canola):
    csv = _write_csv(
        tmp_path / "survey.csv",
        ["ID", "Date_Time", "N", "Disease_Blackleg"],
        ["M1", "2026-05-28", "3.2", "yes"],
        ["M2", "2026-05-28", "2.9", ""],
    )
    loaded = load_for_crop(csv, canola.template_path)

    assert loaded.row_count == 2
    assert loaded.rows[0]["ID"] == "M1"
    assert loaded.mapping.matches["N"] == "N (%)"
