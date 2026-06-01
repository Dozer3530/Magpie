"""Maintenance service: one-click, WAL-safe backups of packages.sqlite.

`packages.sqlite` is the single source of truth and is git-ignored, so once it
holds real weeks it's irreplaceable. `create_backup` writes a consistent
snapshot (via SQLite's online backup API) into `data/backups/`, timestamped.

Run standalone (e.g. from backup.bat):  python -m app.services.maintenance
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from app import db
from app.db import backup_database


def backups_dir() -> Path:
    # Live beside whatever DB is active (read db.DB_PATH at call time so test
    # isolation, which monkeypatches it, points backups at the tmp DB too).
    return Path(db.DB_PATH).parent / "backups"


def create_backup(dest_dir: Path | None = None) -> Path:
    """Write a timestamped snapshot of the DB and return its path.

    Defaults to `data/backups/packages_<YYYYMMDD_HHMMSS>.sqlite`. The snapshot
    is a normal single-file SQLite DB — open it directly, or swap it in for
    `data/packages.sqlite` to restore.
    """
    target_dir = dest_dir or backups_dir()
    target_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = target_dir / f"packages_{ts}.sqlite"
    backup_database(dest)
    return dest


def list_backups(dest_dir: Path | None = None) -> list[Path]:
    """Existing backup files, newest first."""
    target_dir = dest_dir or backups_dir()
    if not target_dir.is_dir():
        return []
    return sorted(target_dir.glob("packages_*.sqlite"), reverse=True)


def main() -> None:
    from app.db import init_db

    init_db()  # harmless if the DB already exists; safe for a cold double-click
    dest = create_backup()
    size_kb = dest.stat().st_size / 1024
    print(f"Backup written: {dest}  ({size_kb:,.0f} KB)")


if __name__ == "__main__":
    main()
