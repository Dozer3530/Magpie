"""Reactive import service: client-scattered points in non-home fields.

The same cumulative Survey123 export also carries one-off "reactive" points the
client scatters across other fields (e.g. "Field F") for ad-hoc scouting. They
ride in the same CSV but are distinguished by the `Where are you?` value: any
field that is NOT a fixed home field (Field 17/18) is reactive.

Unlike the fixed feed there is no stake to GPS-match — each reactive point keeps
its own coordinates and its survey values, stored in `reactive_obs`. It is
Survey123-only (no lab data) and stamped into the lighter `Reactive <Crop>`
templates.

Identity is ephemeral, but numbering is not: a field's points are F1, F2, F3...
and a later batch in the same field **continues** the sequence. The display ID
is DERIVED from the chronological order of all stored points of that field (plus
the batch being previewed), so it is stable and order-independent.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from app.config import PROJECT_ROOT
from app.crops import CROPS, crop_by_code
from app.db import (
    connect,
    list_reactive_all,
    list_reactive_for_week,
    upsert_reactive_row,
)
from app.importers.scouting import CropTranslator, parse_scouting_file


def reactive_template_path(crop_code: str) -> Path:
    """The Survey123-only template for a crop's reactive points (repo root)."""
    return PROJECT_ROOT / f"Reactive {crop_by_code(crop_code).display_name} Template.xlsx"


def _field_prefix(field: str) -> str:
    """'Field F' -> 'F', 'Field AB' -> 'AB'; falls back to the whole value."""
    m = re.match(r"\s*field\s+(.+?)\s*$", field, re.I)
    token = (m.group(1) if m else field).strip()
    return re.sub(r"\s+", "", token).upper() or "X"


def _row_key(field: str, when_iso: str, lat, lon) -> tuple:
    return (field, when_iso, lat, lon)


def _derive_point_ids(rows: list[dict]) -> dict[tuple, str]:
    """Map each row key -> display ID (F1, F2...).

    `rows` are dicts with field/when_iso/lat/lon. Numbering is per field, by
    chronological order across ALL of them (spans weeks and both crops). Sort is
    deterministic so re-imports get identical IDs.
    """
    ordered = sorted(rows, key=lambda r: (r["when_iso"], r["lat"], r["lon"]))
    counters: dict[str, int] = {}
    out: dict[tuple, str] = {}
    for r in ordered:
        fld = r["field"]
        counters[fld] = counters.get(fld, 0) + 1
        out[_row_key(fld, r["when_iso"], r["lat"], r["lon"])] = f"{_field_prefix(fld)}{counters[fld]}"
    return out


def _stored_rows(conn) -> list[dict]:
    return [
        {"field": r["field"], "when_iso": r["when_iso"], "lat": r["lat"], "lon": r["lon"]}
        for r in list_reactive_all(conn)
    ]


def _event_reactive(event) -> list:
    """Non-home rows of an event that carry a crop and coordinates."""
    return [
        r for r in event.rows
        if not r.is_home and r.crop_code and r.lat is not None and r.lon is not None
    ]


def prepare(path) -> dict:
    """Parse the file and build the event list + reactive preview for the UI."""
    parsed = parse_scouting_file(path)
    with connect() as conn:
        stored = _stored_rows(conn)

    events = []
    for ev in parsed.events:
        rrows = _event_reactive(ev)
        batch = [
            {"field": r.field, "when_iso": r.when.isoformat(sep=" "),
             "lat": r.lat, "lon": r.lon}
            for r in rrows
        ]
        # Number against everything already stored PLUS this batch (deduped),
        # so the preview shows the IDs the commit will assign.
        union = {_row_key(d["field"], d["when_iso"], d["lat"], d["lon"]): d
                 for d in stored + batch}
        ids = _derive_point_ids(list(union.values()))

        assignments = []
        crop_counts: dict[str, int] = {}
        fields: list[str] = []
        for r in rrows:
            key = _row_key(r.field, r.when.isoformat(sep=" "), r.lat, r.lon)
            crop_counts[r.crop_code] = crop_counts.get(r.crop_code, 0) + 1
            if r.field not in fields:
                fields.append(r.field)
            assignments.append({
                "time": r.when.strftime("%I:%M %p").lstrip("0"),
                "field": r.field,
                "crop": r.crop_code,
                "point": ids[key],
                "lat": round(r.lat, 6),
                "lon": round(r.lon, 6),
                "scouter": r.scouter,
            })
        events.append({
            "date": ev.day.isoformat(),
            "n_rows": len(rrows),
            "crop_counts": crop_counts,
            "fields": fields,
            "scouters": ev.scouters,
            "assignments": assignments,
        })
    return {"events": events, "skipped_no_date": parsed.skipped_no_date}


def commit(path, iso_week: str, day_iso: str) -> dict:
    """Write one event's reactive rows into `iso_week` (both crops)."""
    parsed = parse_scouting_file(path)
    event = parsed.event(day_iso)
    if event is None:
        raise ValueError(f"No scouting event on {day_iso} in this file.")

    translators = {
        crop.code: CropTranslator(crop.code, reactive_template_path(crop.code))
        for crop in CROPS
    }

    imported: dict[str, int] = {}
    fields: list[str] = []
    unmapped: set[str] = set()
    skipped: list[dict] = []

    with connect() as conn:
        for r in event.rows:
            if r.is_home:
                continue  # fixed-stake point — the scouting feed owns it
            time = r.when.strftime("%I:%M %p").lstrip("0")
            if not r.crop_code:
                skipped.append({"time": time, "field": r.field, "status": "unknown_crop"})
                continue
            if r.lat is None or r.lon is None:
                skipped.append({"time": time, "field": r.field, "status": "no_coords"})
                continue
            values, row_unmapped = translators[r.crop_code].translate(r)
            unmapped.update(row_unmapped)
            upsert_reactive_row(
                conn, r.crop_code, iso_week, r.field,
                r.when.isoformat(sep=" "), r.lat, r.lon, day_iso,
                json.dumps(values),
            )
            imported[r.crop_code] = imported.get(r.crop_code, 0) + 1
            if r.field not in fields:
                fields.append(r.field)

    return {
        "date": day_iso,
        "imported": imported,
        "fields": fields,
        "skipped": skipped,
        "unmapped_columns": sorted(unmapped),
    }


def week_points(crop_code: str, iso_week: str) -> list[dict]:
    """Stored reactive points for (crop, week) with their derived IDs + values.

    Drives the exporters: each dict has point_id, field, lat, lon, and the
    translated `values` map.
    """
    with connect() as conn:
        all_rows = _stored_rows(conn)
        ids = _derive_point_ids(all_rows)
        rows = list_reactive_for_week(conn, crop_code, iso_week)

    out: list[dict] = []
    for r in rows:
        key = _row_key(r["field"], r["when_iso"], r["lat"], r["lon"])
        out.append({
            "point_id": ids.get(key, _field_prefix(r["field"]) + "?"),
            "field": r["field"],
            "lat": r["lat"],
            "lon": r["lon"],
            "values": json.loads(r["values_json"]),
        })
    out.sort(key=lambda d: d["point_id"])
    return out


def has_reactive(crop_code: str, iso_week: str) -> bool:
    with connect() as conn:
        return bool(list_reactive_for_week(conn, crop_code, iso_week))
