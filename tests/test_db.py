"""DB round-trip characterization: save/load, blank->NULL, PK upsert."""
from __future__ import annotations

from app import db
from tests.conftest import seed_week


def test_init_seeds_locations_and_stages(isolated_db):
    with db.connect() as conn:
        canola_locs = db.list_locations(conn, "canola")
        corn_locs = db.list_locations(conn, "corn")
        stages = db.list_growth_stages(conn, "canola")

    assert [r["location_id"] for r in canola_locs] == [f"M{i}" for i in range(1, 10)]
    assert [r["location_id"] for r in corn_locs] == [f"L{i}" for i in range(1, 10)]
    assert len(stages) > 0


def test_save_load_round_trip(isolated_db):
    week = seed_week()
    # Use unit-free column names so the test doesn't depend on unit text.
    values = {
        "Date_Time": "2026-05-28 09:00",
        "Disease_Blackleg": "yes",
        "Disease_Blackleg_Severity": "Med",
        "ReportNo": "PT2R-1234",
    }
    with db.connect() as conn:
        db.save_obs_row(conn, "canola", week, "M1", values)

    with db.connect() as conn:
        loaded = db.load_obs_row(conn, "canola", week, "M1")

    for k, v in values.items():
        assert loaded[k] == v


def test_blank_stored_as_null_loads_as_empty(isolated_db):
    week = seed_week()
    with db.connect() as conn:
        db.save_obs_row(conn, "canola", week, "M2", {"Disease_Blackleg": ""})

    # Blank -> NULL in storage, NULL -> "" on load.
    with db.connect() as conn:
        row = conn.execute(
            'SELECT "Disease_Blackleg" FROM obs_canola '
            'WHERE iso_week = ? AND location_id = ?',
            (week, "M2"),
        ).fetchone()
        assert row["Disease_Blackleg"] is None

        loaded = db.load_obs_row(conn, "canola", week, "M2")
        assert loaded["Disease_Blackleg"] == ""


def test_upsert_overwrites_same_pk(isolated_db):
    week = seed_week()
    with db.connect() as conn:
        db.save_obs_row(conn, "canola", week, "M1", {"ReportNo": "first"})
        db.save_obs_row(conn, "canola", week, "M1", {"ReportNo": "second"})

    with db.connect() as conn:
        loaded = db.load_obs_row(conn, "canola", week, "M1")
        rows = db.list_obs_for_week(conn, "canola", week)

    assert loaded["ReportNo"] == "second"
    # Still a single row for that location (upsert, not insert).
    assert len([r for r in rows if r["location_id"] == "M1"]) == 1


def test_load_missing_row_is_empty_dict(isolated_db):
    week = seed_week()
    with db.connect() as conn:
        assert db.load_obs_row(conn, "canola", week, "M9") == {}


def test_delete_week_cascades(isolated_db):
    week = seed_week()
    with db.connect() as conn:
        db.save_obs_row(conn, "canola", week, "M1", {"ReportNo": "x"})
    with db.connect() as conn:
        db.delete_week(conn, week)
    with db.connect() as conn:
        assert db.list_obs_for_week(conn, "canola", week) == []
