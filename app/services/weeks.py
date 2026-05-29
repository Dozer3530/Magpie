"""Week-management service: ISO-week calc + CRUD over the `weeks` table.

Extracted verbatim from main_window's date logic so both frontends share
identical week behaviour (auto-create on first launch, new/delete week).
"""
from __future__ import annotations

from datetime import date

from app import image_storage
from app.crops import CROPS
from app.db import (
    connect,
    delete_week as _delete_week,
    list_locations,
    list_obs_for_week,
    list_weeks,
    rename_week as _rename_week,
    upsert_week,
)
from app.schema import field_page_names, lab_page_names, read_template_fields

# Characters that would break the week tag when used in file paths / export
# filenames (the tag is stamped into exports/<week>/, Canola_<week>.xlsx, etc.).
_ILLEGAL_TAG_CHARS = set('<>:"/\\|?*')


def current_iso_week() -> str:
    """The current ISO week as a `YYYY-Www` tag (e.g. `2026-W22`)."""
    iso_year, iso_week, _ = date.today().isocalendar()
    return f"{iso_year}-W{iso_week:02d}"


def list_week_tags() -> list[str]:
    """All week tags, newest first (the order list_weeks returns)."""
    with connect() as conn:
        return [r["iso_week"] for r in list_weeks(conn)]


def list_week_rows() -> list[dict]:
    """All week rows as plain dicts (iso_week, label, created_at)."""
    with connect() as conn:
        return [dict(r) for r in list_weeks(conn)]


def ensure_current_week() -> str | None:
    """First-launch convenience: if no weeks exist, seed the current ISO week.

    Returns the created tag, or None if weeks already existed.
    """
    with connect() as conn:
        if list_weeks(conn):
            return None
        tag = current_iso_week()
        upsert_week(conn, tag)
        return tag


def create_week(tag: str, label: str | None = None) -> None:
    with connect() as conn:
        upsert_week(conn, tag, label)


def delete_week(tag: str) -> None:
    """Remove a week; obs rows cascade-delete for every crop."""
    with connect() as conn:
        _delete_week(conn, tag)


def rename_week(old: str, new: str) -> str:
    """Rename a week's code (its DB key) from `old` to `new`.

    Carries every crop's obs rows and moves the on-disk image folders so photos
    stay resolvable. The new code is free-form but must be safe to embed in
    export filenames / folder paths. Returns the cleaned new tag.

    Raises ValueError on an empty / illegal name, or if `new` collides with a
    different existing week.
    """
    new = (new or "").strip()
    if not new:
        raise ValueError("Week name can't be empty.")
    bad = sorted(_ILLEGAL_TAG_CHARS & set(new))
    if bad:
        raise ValueError(
            "Week name can't contain any of these characters: " + " ".join(bad)
        )
    if new == old:
        return old
    with connect() as conn:
        # db.rename_week raises if `new` already exists or `old` doesn't.
        _rename_week(conn, old, new)
    # DB committed — now move the image folders to match the new code.
    image_storage.rename_week_dirs(old, new)
    return new


# ---- Multi-week progress (Field vs Lab) ------------------------------------

def all_weeks_progress() -> list[dict]:
    """Per-week, per-crop Field (Survey123) vs Lab (PT2R) completeness.

    Field obs arrive early each week; lab results lag — so each week is scored
    on two independent tracks so you can see which weeks have obs in but are
    still waiting on lab data.

    For each (week, crop):
      *_expected  = #data columns on that track × #locations
      *_filled    = #non-empty cells across those columns
      *_locations = #locations with at least one filled cell on that track
    """
    # Per-crop column sets + locations are week-independent — compute once.
    crop_meta: dict[str, dict] = {}
    with connect() as conn:
        for crop in CROPS:
            fields = read_template_fields(crop.template_path)
            crop_meta[crop.code] = {
                "display_name": crop.display_name,
                "field_names": field_page_names(fields),
                "lab_names": lab_page_names(fields),
                "n_locations": len(list_locations(conn, crop.code)),
            }
        week_rows = [dict(r) for r in list_weeks(conn)]

        out: list[dict] = []
        for wk in week_rows:
            iso = wk["iso_week"]
            crops_out = []
            for crop in CROPS:
                meta = crop_meta[crop.code]
                fnames, lnames = meta["field_names"], meta["lab_names"]
                n_locs = meta["n_locations"]
                obs = list_obs_for_week(conn, crop.code, iso)

                field_filled = lab_filled = 0
                field_locs = lab_locs = 0
                for row in obs:
                    d = dict(row)
                    ff = sum(1 for n in fnames if d.get(n) not in (None, ""))
                    lf = sum(1 for n in lnames if d.get(n) not in (None, ""))
                    field_filled += ff
                    lab_filled += lf
                    field_locs += 1 if ff else 0
                    lab_locs += 1 if lf else 0

                crops_out.append({
                    "crop_code": crop.code,
                    "display_name": meta["display_name"],
                    "total_locations": n_locs,
                    "field_filled": field_filled,
                    "field_expected": len(fnames) * n_locs,
                    "field_locations": field_locs,
                    "lab_filled": lab_filled,
                    "lab_expected": len(lnames) * n_locs,
                    "lab_locations": lab_locs,
                })
            out.append({
                "iso_week": iso,
                "label": wk.get("label"),
                "created_at": wk.get("created_at"),
                "crops": crops_out,
            })
    return out
