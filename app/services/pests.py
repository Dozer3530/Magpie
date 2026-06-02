"""Pest ID service: import a week's slice, report status, build the export block.

The Pest ID sheet is a living per-field log; on import the user picks which
sheet-week to extract and it attaches to the app's currently-selected ISO week.
Crop is auto-detected from the point prefix in the file. Bug types vary, so
they're stored as a JSON object per (crop, week, location) in `pest_obs`.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field as dc_field

from app.db import (
    clear_pest_for_week,
    connect,
    list_locations,
    list_pest_for_week,
    upsert_pest_row,
)
from app.importers.pest import ParsedPest, parse_pest_file


@dataclass
class PestImportResult:
    crop_code: str
    week_index: int
    week_label: str
    imported: int            # locations written
    cards_completed: int
    bug_types: list[str] = dc_field(default_factory=list)


def prepare(path) -> ParsedPest:
    return parse_pest_file(path)


def week_choices(parsed: ParsedPest) -> list[dict]:
    """The selectable weeks for the import dropdown."""
    return [
        {
            "index": w.index,
            "date": w.date,
            "cards_completed": w.cards_completed,
            "total": len(w.points),
            "bug_types": w.bug_types_present,
        }
        for w in parsed.weeks
    ]


def commit(path, iso_week: str, week_index: int) -> PestImportResult:
    """Store one sheet-week's slice under (detected crop, iso_week).

    Replaces any existing pest data for that (crop, week) — re-importing the
    same week is idempotent.
    """
    parsed = parse_pest_file(path)
    wk = parsed.week(week_index)
    if wk is None:
        raise ValueError(f"Week {week_index} not found in the pest file.")

    crop = parsed.crop_code
    with connect() as conn:
        clear_pest_for_week(conn, crop, iso_week)
        for loc, point in wk.points.items():
            upsert_pest_row(
                conn, crop, iso_week, loc,
                card_completed=point.card_completed,
                source_date=point.date,
                source_week=wk.index,
                bugs_json=json.dumps(point.bugs),
            )
    return PestImportResult(
        crop_code=crop,
        week_index=wk.index,
        week_label=wk.date or f"Week {wk.index}",
        imported=len(wk.points),
        cards_completed=wk.cards_completed,
        bug_types=wk.bug_types_present,
    )


def pest_status(crop_code: str, iso_week: str) -> dict:
    """The in-app 'uploaded' indicator for (crop, week)."""
    with connect() as conn:
        rows = [dict(r) for r in list_pest_for_week(conn, crop_code, iso_week)]
        total_locations = len(list_locations(conn, crop_code))
    bug_types: list[str] = []
    cards = 0
    source_week = source_date = None
    for r in rows:
        if r["card_completed"]:
            cards += 1
        source_week = r.get("source_week")
        source_date = r.get("source_date")
        for b, v in json.loads(r["bugs_json"] or "{}").items():
            if str(v).strip() and b not in bug_types:
                bug_types.append(b)
    return {
        "uploaded": bool(rows),
        "cards_completed": cards,
        "total_locations": total_locations,
        "bug_types": bug_types,
        "source_week": source_week,
        "source_date": source_date,
    }


def export_block(crop_code: str, iso_week: str) -> tuple[list[str], dict[str, dict[str, str]]]:
    """Bug columns to add to the export for (crop, week).

    Returns (ordered bug names that have a value somewhere this week,
    {location_id: {bug: value}}). Empty list → no pest block in the export.
    """
    with connect() as conn:
        rows = [dict(r) for r in list_pest_for_week(conn, crop_code, iso_week)]

    by_loc: dict[str, dict[str, str]] = {}
    ordered: list[str] = []
    for r in rows:
        bugs = json.loads(r["bugs_json"] or "{}")
        clean = {b: str(v).strip() for b, v in bugs.items() if str(v).strip()}
        if clean:
            by_loc[r["location_id"]] = clean
            for b in clean:
                if b not in ordered:
                    ordered.append(b)
    return ordered, by_loc
