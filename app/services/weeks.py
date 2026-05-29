"""Week-management service: ISO-week calc + CRUD over the `weeks` table.

Extracted verbatim from main_window's date logic so both frontends share
identical week behaviour (auto-create on first launch, new/delete week).
"""
from __future__ import annotations

from datetime import date

from app.db import connect, delete_week as _delete_week, list_weeks, upsert_week


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
