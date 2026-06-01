"""Tests for week renaming + the multi-week Field/Lab progress dashboard.

Covers the shared-core additions:
  * db.rename_week / services.weeks.rename_week — PK migration carrying obs
    rows + image folders, with validation.
  * services.weeks.all_weeks_progress — two-track Field vs Lab coverage.
  * schema.page_of agrees with build_form_schema's section pages.
Reuses the `isolated_db` fixture (tmp DB + tmp IMAGES_ROOT).
"""
from __future__ import annotations

import pytest

from app import db, image_storage
from app.schema import (
    field_page_names,
    lab_page_names,
    page_of,
    read_template_fields,
)
from app.services import observations as obs_service
from app.services import weeks as weeks_service


def _name(crop, key):
    for f in read_template_fields(crop.template_path):
        if f.key == key:
            return f.name
    raise KeyError(key)


# ---- Field/Lab split is the single source of truth -------------------------

def test_page_of_matches_form_schema_sections(canola):
    """page_of() must agree with how build_form_schema groups field vs lab."""
    fields = {f.name: f for f in read_template_fields(canola.template_path)}
    schema = obs_service.build_form_schema("canola")
    for sec in schema.sections:
        for f in sec.fields:
            if f.name in ("ID", "Location", "Images"):
                continue
            assert page_of(fields[f.name]) == sec.page, f"{f.name} page mismatch"


def test_field_lab_name_sets_disjoint(canola):
    fields = read_template_fields(canola.template_path)
    fnames, lnames = field_page_names(fields), lab_page_names(fields)
    assert fnames and lnames
    assert fnames.isdisjoint(lnames)
    # nutrient value + rate are lab; TDR + disease are field
    assert _name(canola, "N") in lnames
    assert "Disease_Blackleg" in fnames


# ---- rename_week -----------------------------------------------------------

def test_rename_week_carries_obs_and_images(isolated_db, canola):
    weeks_service.create_week("2026-W22", label="bloom")
    n_name = _name(canola, "N")
    obs_service.save("canola", "2026-W22", "M1", {n_name: "3.2"})

    # a photo folder for this (crop, week)
    img_dir = image_storage.IMAGES_ROOT / "canola" / "2026-W22" / "M1"
    img_dir.mkdir(parents=True)
    (img_dir / "x.jpg").write_bytes(b"fake")

    weeks_service.rename_week("2026-W22", "Bloom-1")

    tags = weeks_service.list_week_tags()
    assert "Bloom-1" in tags and "2026-W22" not in tags
    # label + obs carried over
    row = obs_service.load("canola", "Bloom-1", "M1")
    assert row[n_name] == "3.2"
    assert not obs_service.load("canola", "2026-W22", "M1")  # old gone
    rows = [dict(r) for r in weeks_service.list_week_rows()]
    assert any(r["iso_week"] == "Bloom-1" and r["label"] == "bloom" for r in rows)
    # image folder moved
    assert (image_storage.IMAGES_ROOT / "canola" / "Bloom-1" / "M1" / "x.jpg").exists()
    assert not (image_storage.IMAGES_ROOT / "canola" / "2026-W22").exists()


def test_rename_week_rejects_duplicate(isolated_db):
    weeks_service.create_week("2026-W22")
    weeks_service.create_week("2026-W23")
    with pytest.raises(ValueError):
        weeks_service.rename_week("2026-W22", "2026-W23")


@pytest.mark.parametrize("bad", ["", "   ", "bad/name", "a:b", "x|y", "q?z"])
def test_rename_week_rejects_bad_names(isolated_db, bad):
    weeks_service.create_week("2026-W22")
    with pytest.raises(ValueError):
        weeks_service.rename_week("2026-W22", bad)


def test_rename_week_noop_same_name(isolated_db):
    weeks_service.create_week("2026-W22")
    assert weeks_service.rename_week("2026-W22", "2026-W22") == "2026-W22"


# ---- all_weeks_progress ----------------------------------------------------

def test_create_backup_is_a_valid_consistent_copy(isolated_db, canola, tmp_path):
    import sqlite3

    from app.services import maintenance

    weeks_service.create_week("2026-W22")
    n_name = _name(canola, "N")
    obs_service.save("canola", "2026-W22", "M1", {n_name: "9.9"})

    dest_dir = tmp_path / "bk"
    backup = maintenance.create_backup(dest_dir=dest_dir)
    assert backup.exists() and backup.parent == dest_dir
    assert maintenance.list_backups(dest_dir) == [backup]

    # The snapshot is a normal SQLite DB carrying the just-saved value.
    conn = sqlite3.connect(backup)
    try:
        row = conn.execute(
            'SELECT "' + n_name + '" FROM obs_canola WHERE iso_week=? AND location_id=?',
            ("2026-W22", "M1"),
        ).fetchone()
    finally:
        conn.close()
    assert row[0] == "9.9"


def test_all_weeks_progress_two_tracks(isolated_db, canola):
    weeks_service.create_week("2026-W22")
    n_name = _name(canola, "N")          # lab column
    # M1: field-only (disease presence) ; M2: lab-only (a nutrient)
    obs_service.save("canola", "2026-W22", "M1", {"Disease_Blackleg": "yes"})
    obs_service.save("canola", "2026-W22", "M2", {n_name: "3.0"})

    prog = weeks_service.all_weeks_progress()
    wk = next(w for w in prog if w["iso_week"] == "2026-W22")
    canola_p = next(c for c in wk["crops"] if c["crop_code"] == "canola")

    assert canola_p["total_locations"] == 9
    assert canola_p["field_locations"] == 1   # M1 only
    assert canola_p["lab_locations"] == 1      # M2 only
    assert canola_p["field_filled"] == 1
    assert canola_p["lab_filled"] == 1
    assert canola_p["field_expected"] == len(field_page_names(read_template_fields(canola.template_path))) * 9
