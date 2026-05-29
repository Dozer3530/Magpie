"""Shared pytest fixtures.

These tests are *characterization* tests: they pin down the current behavior
of Magpie's UI-agnostic core (db / schema / importers / exporters) so the
upcoming service-layer extraction can be proven byte-for-byte equivalent.

Isolation strategy
------------------
`app.db.connect()` resolves the module-global `DB_PATH` at call time, so
monkeypatching `app.db.DB_PATH` to a tmp file redirects *all* DB access —
including the exporters, which import `connect` from `app.db`. We also point
`app.image_storage.IMAGES_ROOT` at a tmp dir and stub `app.db.ensure_app_dirs`
so nothing touches the real `data/` folder.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app import db, image_storage
from app.crops import crop_by_code


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    """Fresh, initialized SQLite DB + image store under tmp_path.

    Yields the tmp_path root so tests can build export paths under it.
    """
    db_path = tmp_path / "packages.sqlite"
    images_root = tmp_path / "images"

    # Redirect the DB and image storage to tmp. connect() reads the global
    # at call time, so patching the name on app.db is enough.
    monkeypatch.setattr(db, "DB_PATH", db_path)
    monkeypatch.setattr(db, "ensure_app_dirs", lambda: db_path.parent.mkdir(parents=True, exist_ok=True))
    monkeypatch.setattr(image_storage, "IMAGES_ROOT", images_root)

    db.init_db()
    return tmp_path


@pytest.fixture
def canola():
    return crop_by_code("canola")


@pytest.fixture
def corn():
    return crop_by_code("corn")


def seed_week(week: str = "2026-W22") -> str:
    """Insert a week row (PK for obs FK). Caller must be inside isolated_db."""
    with db.connect() as conn:
        db.upsert_week(conn, week)
    return week
