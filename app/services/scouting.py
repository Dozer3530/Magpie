"""Scouting import service: GPS-join the real Survey123 export to the points.

Upload → pick a scouting event (calendar date) → each row is matched to the
nearest monitoring point of its crop → translated → written into the selected
week. One commit fills BOTH crops (the scout walks both fields in one event).

Assignment-correctness guarantees (measured on the real fields: stakes ≥106 m
apart, submissions 3–18 m from their stake):
  * hard tolerance: a row farther than TOLERANCE_M from every stake is skipped
    and reported with its distance — never guessed;
  * ambiguity guard: if the second-nearest stake is closer than
    AMBIGUITY_RATIO × the nearest distance, the row is flagged, not written
    (can't trigger while stakes are ≥2× the tolerance apart — pure insurance);
  * one row per point per commit: duplicates resolve latest-timestamp-wins and
    are reported as superseded;
  * the same assignment computation feeds the pre-commit preview table, so
    what you approve is exactly what's written.
"""
from __future__ import annotations

import math
from pathlib import Path

from app.crops import CROPS, crop_by_code
from app.db import connect, list_locations, save_obs_row
from app.importers.scouting import (
    CropTranslator,
    ParsedScouting,
    ScoutEvent,
    parse_scouting_file,
)

TOLERANCE_M = 50.0
AMBIGUITY_RATIO = 2.0


def _dist_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    # Equirectangular approximation — exact enough at field scale (<1 km).
    kx = 111_320 * math.cos(math.radians(lat1))
    ky = 110_540
    return math.hypot((lon2 - lon1) * kx, (lat2 - lat1) * ky)


def _locations_by_crop() -> dict[str, list[tuple[str, float, float]]]:
    out: dict[str, list[tuple[str, float, float]]] = {}
    with connect() as conn:
        for crop in CROPS:
            out[crop.code] = [
                (r["location_id"], r["lat"], r["lon"])
                for r in list_locations(conn, crop.code)
            ]
    return out


def _assign(event: ScoutEvent, locs_by_crop: dict) -> list[dict]:
    """Compute the per-row assignment table (the preview AND the commit input)."""
    rows: list[dict] = []
    for r in event.rows:
        a = {
            "when": r.when.isoformat(sep=" "),
            "time": r.when.strftime("%I:%M %p").lstrip("0"),
            "crop": r.crop_code,
            "scouter": r.scouter,
            "point": None,
            "dist_m": None,
            "second_point": None,
            "second_dist_m": None,
            "status": "matched",
            "superseded": False,
            "field": r.field,
            "_row": r,
        }
        if not r.is_home:
            # Belongs to the Reactive feed (client-scattered point) — never
            # GPS-matched to a fixed stake here. Keeps the two feeds disjoint.
            a["status"] = "other_field"
        elif r.crop_code is None:
            a["status"] = "unknown_crop"
        elif r.lat is None or r.lon is None:
            a["status"] = "no_coords"
        else:
            ranked = sorted(
                ((_dist_m(r.lat, r.lon, lat, lon), pid) for pid, lat, lon in locs_by_crop[r.crop_code])
            )
            (d1, p1) = ranked[0]
            a["point"], a["dist_m"] = p1, round(d1, 1)
            if len(ranked) > 1:
                a["second_point"], a["second_dist_m"] = ranked[1][1], round(ranked[1][0], 1)
            if d1 > TOLERANCE_M:
                a["status"] = "too_far"
                a["point"] = None
            elif len(ranked) > 1 and ranked[1][0] < AMBIGUITY_RATIO * d1:
                a["status"] = "ambiguous"
                a["point"] = None
        rows.append(a)

    # Latest-timestamp-wins per (crop, point).
    best: dict[tuple[str, str], dict] = {}
    for a in rows:
        if a["status"] != "matched":
            continue
        key = (a["crop"], a["point"])
        prev = best.get(key)
        if prev is None or a["_row"].when > prev["_row"].when:
            if prev is not None:
                prev["superseded"] = True
            best[key] = a
        else:
            a["superseded"] = True
    return rows


def _public(assignments: list[dict]) -> list[dict]:
    return [{k: v for k, v in a.items() if k != "_row"} for a in assignments]


def prepare(path) -> dict:
    """Parse the file and build the event list + assignment preview for the UI."""
    parsed: ParsedScouting = parse_scouting_file(path)
    locs = _locations_by_crop()
    events = []
    for ev in parsed.events:
        assignments = _assign(ev, locs)
        events.append({
            "date": ev.day.isoformat(),
            "n_rows": len(ev.rows),
            "crop_counts": ev.crop_counts,
            "scouters": ev.scouters,
            "matched": sum(1 for a in assignments if a["status"] == "matched" and not a["superseded"]),
            "assignments": _public(assignments),
        })
    return {"events": events, "skipped_no_date": parsed.skipped_no_date}


def commit(path, iso_week: str, day_iso: str) -> dict:
    """Write one event's matched rows into `iso_week` (both crops at once)."""
    parsed = parse_scouting_file(path)
    event = parsed.event(day_iso)
    if event is None:
        raise ValueError(f"No scouting event on {day_iso} in this file.")

    assignments = _assign(event, _locations_by_crop())
    translators = {
        crop.code: CropTranslator(crop.code, crop_by_code(crop.code).template_path)
        for crop in CROPS
    }

    imported: dict[str, int] = {}
    unmapped: set[str] = set()
    skipped: list[dict] = []
    superseded = 0

    with connect() as conn:
        for a in assignments:
            if a["status"] == "other_field":
                continue  # reactive point — not this feed's job, not a problem
            if a["superseded"]:
                superseded += 1
                continue
            if a["status"] != "matched":
                skipped.append({k: a[k] for k in ("time", "crop", "status", "dist_m", "second_point")})
                continue
            values, row_unmapped = translators[a["crop"]].translate(a["_row"])
            unmapped.update(row_unmapped)
            if not values:
                skipped.append({"time": a["time"], "crop": a["crop"], "status": "empty", "dist_m": a["dist_m"], "second_point": None})
                continue
            save_obs_row(conn, a["crop"], iso_week, a["point"], values)
            imported[a["crop"]] = imported.get(a["crop"], 0) + 1

    return {
        "date": day_iso,
        "imported": imported,
        "skipped": skipped,
        "superseded": superseded,
        "unmapped_columns": sorted(unmapped),
    }
