"""SQLite layer.

The DB lives at `data/packages.sqlite`. Schema is partly hand-rolled (shared
tables) and partly generated from each crop's template (per-crop wide
`obs_<crop>` tables). The template is the source of truth — re-running
`init_db()` is safe (idempotent) and will add new columns introduced to a
template since last run.

Calling shape:
    init_db()                            # idempotent; safe at every launch
    with connect() as conn: ...          # short-lived transactions

We deliberately store every value as TEXT so cells round-trip byte-equivalent
to the templates (e.g. disease presence = literal "yes" or blank, severity =
"Low" / "Med" / "High"). Numeric coercion happens at the UI / import edges.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from app.config import DB_PATH, ensure_app_dirs
from app.crops import CROPS, CropConfig
from app.schema import read_template_fields, read_template_locations


# ---- Connections ------------------------------------------------------------

def _quote_ident(name: str) -> str:
    """Quote a SQLite identifier (column/table name) safely.

    Template headers can contain `.`, `/`, `%`, `'`, spaces — none of which
    are SQL-injection vectors here (they come from files we ship), but they
    do need quoting to be valid identifiers.
    """
    return '"' + name.replace('"', '""') + '"'


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    ensure_app_dirs()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    # WAL lets readers and a writer coexist without blocking — friendlier when
    # the desktop app and the local web server both touch packages.sqlite. It
    # is NOT a licence for two simultaneous editors (still run one frontend at
    # a time); it just makes incidental concurrent reads painless. The mode is
    # persisted on the DB file, so setting it per-connect is idempotent.
    conn.execute("PRAGMA journal_mode = WAL")
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def backup_database(dest: Path) -> None:
    """Write a consistent snapshot of the live DB to `dest`.

    Uses SQLite's online backup API rather than a file copy, so the snapshot is
    transaction-consistent and folds in any pending WAL pages — copying just the
    `.sqlite` file while a WAL exists can miss the most recent writes. `dest`'s
    parent must already exist.
    """
    ensure_app_dirs()
    src = sqlite3.connect(DB_PATH)
    try:
        dst = sqlite3.connect(dest)
        try:
            with dst:
                src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()


# ---- Schema -----------------------------------------------------------------

SHARED_SCHEMA = [
    """
    CREATE TABLE IF NOT EXISTS crops (
        code           TEXT PRIMARY KEY,
        display_name   TEXT NOT NULL,
        template_path  TEXT NOT NULL,
        location_prefix TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS locations (
        crop_code   TEXT NOT NULL,
        location_id TEXT NOT NULL,
        lat         REAL NOT NULL,
        lon         REAL NOT NULL,
        PRIMARY KEY (crop_code, location_id),
        FOREIGN KEY (crop_code) REFERENCES crops(code)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS growth_stages (
        crop_code   TEXT NOT NULL,
        code        TEXT NOT NULL,
        description TEXT NOT NULL,
        sort_order  INTEGER NOT NULL,
        PRIMARY KEY (crop_code, code),
        FOREIGN KEY (crop_code) REFERENCES crops(code)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS weeks (
        iso_week   TEXT PRIMARY KEY,
        label      TEXT,
        created_at TEXT NOT NULL DEFAULT (datetime('now'))
    )
    """,
    # Pest ID feed: a living per-field bug log. Bug types vary week to week,
    # so counts are stored as a JSON object rather than fixed columns. One row
    # per (crop, week, location). card_completed drives the in-app "uploaded"
    # indicator; bugs_json feeds the colored export block.
    """
    CREATE TABLE IF NOT EXISTS pest_obs (
        crop_code      TEXT NOT NULL,
        iso_week       TEXT NOT NULL,
        location_id    TEXT NOT NULL,
        card_completed INTEGER NOT NULL DEFAULT 0,
        source_date    TEXT,
        source_week    INTEGER,
        bugs_json      TEXT NOT NULL DEFAULT '{}',
        PRIMARY KEY (crop_code, iso_week, location_id),
        FOREIGN KEY (iso_week) REFERENCES weeks(iso_week) ON DELETE CASCADE
    )
    """,
    # "Reactive" feed: client-scattered points in non-home fields. Ephemeral
    # locations (no fixed stake), so the point carries its own GPS and survey
    # values (stored as JSON like pest_obs). Identity = (crop, week, field,
    # capture time, coords); the display ID (F1, F2...) is DERIVED from
    # chronological order per field, never stored. Survey123-only — no lab data.
    """
    CREATE TABLE IF NOT EXISTS reactive_obs (
        crop_code   TEXT NOT NULL,
        iso_week    TEXT NOT NULL,
        field       TEXT NOT NULL,
        when_iso    TEXT NOT NULL,
        lat         REAL,
        lon         REAL,
        source_date TEXT,
        values_json TEXT NOT NULL DEFAULT '{}',
        PRIMARY KEY (crop_code, iso_week, field, when_iso, lat, lon),
        FOREIGN KEY (iso_week) REFERENCES weeks(iso_week) ON DELETE CASCADE
    )
    """,
]


def init_db() -> None:
    """Create or upgrade the schema. Safe to run on every launch."""
    with connect() as conn:
        for stmt in SHARED_SCHEMA:
            conn.execute(stmt)

        for crop in CROPS:
            _upsert_crop_row(conn, crop)
            _seed_locations(conn, crop)
            _seed_growth_stages(conn, crop)
            _create_or_upgrade_obs_table(conn, crop)


def _upsert_crop_row(conn: sqlite3.Connection, crop: CropConfig) -> None:
    conn.execute(
        """
        INSERT INTO crops (code, display_name, template_path, location_prefix)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(code) DO UPDATE SET
            display_name = excluded.display_name,
            template_path = excluded.template_path,
            location_prefix = excluded.location_prefix
        """,
        (crop.code, crop.display_name, str(crop.template_path), crop.location_prefix),
    )


def _seed_locations(conn: sqlite3.Connection, crop: CropConfig) -> None:
    locs = read_template_locations(crop.template_path)
    conn.executemany(
        """
        INSERT INTO locations (crop_code, location_id, lat, lon)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(crop_code, location_id) DO UPDATE SET
            lat = excluded.lat,
            lon = excluded.lon
        """,
        [(crop.code, loc_id, lat, lon) for (loc_id, lat, lon) in locs],
    )


def _seed_growth_stages(conn: sqlite3.Connection, crop: CropConfig) -> None:
    # Wipe and re-seed: the canonical source is the per-crop Python module,
    # so an edit there is authoritative.
    conn.execute("DELETE FROM growth_stages WHERE crop_code = ?", (crop.code,))
    rows = [
        (crop.code, code, desc, i)
        for i, (code, desc) in enumerate(crop.growth_stages())
    ]
    conn.executemany(
        """
        INSERT INTO growth_stages (crop_code, code, description, sort_order)
        VALUES (?, ?, ?, ?)
        """,
        rows,
    )


def _create_or_upgrade_obs_table(conn: sqlite3.Connection, crop: CropConfig) -> None:
    """Create obs_<crop> with one column per template header.

    If the table already exists, ADD COLUMN for any new headers introduced
    since last run. Existing columns are left untouched.
    """
    fields = read_template_fields(crop.template_path)
    table = _quote_ident(crop.obs_table)

    # Primary-key columns are iso_week + location_id.
    # Every template column becomes a TEXT column. We keep the original
    # header text as the column name (quoted), so writes/exports map 1:1.
    create_cols = [
        '"iso_week" TEXT NOT NULL',
        '"location_id" TEXT NOT NULL',
    ]
    for f in fields:
        # ID and Location are template-header columns too, but we already
        # have location_id; the template's "Location" column is regenerated
        # at export time from `locations.lat/lon`. Skip them in the obs table.
        if f.name == "ID" or f.name == "Location":
            continue
        create_cols.append(f"{_quote_ident(f.name)} TEXT")
    create_cols.append('PRIMARY KEY ("iso_week", "location_id")')
    create_cols.append(
        'FOREIGN KEY ("iso_week") REFERENCES weeks("iso_week") ON DELETE CASCADE'
    )

    conn.execute(f"CREATE TABLE IF NOT EXISTS {table} (\n  "
                 + ",\n  ".join(create_cols) + "\n)")

    # ALTER ADD COLUMN for new headers.
    existing_cols = {
        row["name"]
        for row in conn.execute(f"PRAGMA table_info({table})")
    }
    for f in fields:
        if f.name in ("ID", "Location"):
            continue
        if f.name not in existing_cols:
            conn.execute(
                f"ALTER TABLE {table} ADD COLUMN {_quote_ident(f.name)} TEXT"
            )


# ---- Read helpers (small surface; UI will grow this) -----------------------

def list_crops(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return list(conn.execute(
        "SELECT code, display_name FROM crops ORDER BY display_name"
    ))


def list_locations(conn: sqlite3.Connection, crop_code: str) -> list[sqlite3.Row]:
    return list(conn.execute(
        """
        SELECT location_id, lat, lon
        FROM locations
        WHERE crop_code = ?
        ORDER BY location_id
        """,
        (crop_code,),
    ))


def list_growth_stages(conn: sqlite3.Connection, crop_code: str) -> list[sqlite3.Row]:
    return list(conn.execute(
        """
        SELECT code, description
        FROM growth_stages
        WHERE crop_code = ?
        ORDER BY sort_order
        """,
        (crop_code,),
    ))


def list_weeks(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return list(conn.execute(
        "SELECT iso_week, label, created_at FROM weeks ORDER BY iso_week DESC"
    ))


def upsert_week(conn: sqlite3.Connection, iso_week: str, label: str | None = None) -> None:
    conn.execute(
        """
        INSERT INTO weeks (iso_week, label)
        VALUES (?, ?)
        ON CONFLICT(iso_week) DO UPDATE SET label = COALESCE(excluded.label, weeks.label)
        """,
        (iso_week, label),
    )


# ---- Per-row obs helpers ---------------------------------------------------

def load_obs_row(
    conn: sqlite3.Connection,
    crop_code: str,
    iso_week: str,
    location_id: str,
) -> dict[str, str]:
    """Return a dict of {column_name: value_as_text} for one observation row.

    Empty dict if no row exists yet for that (week, location).
    """
    table = _quote_ident(f"obs_{crop_code}")
    row = conn.execute(
        f'SELECT * FROM {table} WHERE "iso_week" = ? AND "location_id" = ?',
        (iso_week, location_id),
    ).fetchone()
    if row is None:
        return {}
    return {k: ("" if row[k] is None else str(row[k])) for k in row.keys()}


def save_obs_row(
    conn: sqlite3.Connection,
    crop_code: str,
    iso_week: str,
    location_id: str,
    values: dict[str, str],
) -> None:
    """Upsert one observation row.

    `values` maps template-header column names to their text representation.
    Blank strings are stored as NULL so SQLite's COALESCE/joins work cleanly.
    """
    table = _quote_ident(f"obs_{crop_code}")

    # Filter out the PK columns if a caller accidentally passed them.
    cleaned = {
        k: (None if v == "" else v)
        for k, v in values.items()
        if k not in ("iso_week", "location_id")
    }

    cols = ['"iso_week"', '"location_id"'] + [_quote_ident(c) for c in cleaned.keys()]
    placeholders = ", ".join(["?"] * len(cols))
    update_clause = ", ".join(
        f"{_quote_ident(c)} = excluded.{_quote_ident(c)}" for c in cleaned.keys()
    ) or '"iso_week" = excluded."iso_week"'  # fallback no-op if values empty

    sql = (
        f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({placeholders}) "
        f"ON CONFLICT(\"iso_week\", \"location_id\") DO UPDATE SET {update_clause}"
    )
    params = [iso_week, location_id] + list(cleaned.values())
    conn.execute(sql, params)


def delete_week(conn: sqlite3.Connection, iso_week: str) -> None:
    """Remove a week and cascade-delete its obs rows for every crop."""
    # FK ON DELETE CASCADE on obs_<crop>.iso_week handles per-crop rows.
    conn.execute("DELETE FROM weeks WHERE iso_week = ?", (iso_week,))


def week_exists(conn: sqlite3.Connection, iso_week: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM weeks WHERE iso_week = ?", (iso_week,)
    ).fetchone() is not None


def rename_week(conn: sqlite3.Connection, old: str, new: str) -> None:
    """Change a week's primary key from `old` to `new`, carrying its obs rows.

    The `iso_week` PK is referenced by every `obs_<crop>` table (FK is ON DELETE
    CASCADE, not ON UPDATE), so we can't just UPDATE the PK in place. Instead we
    order the operations so the FK is satisfied at every step:

      1. copy the `weeks` row to the new PK (preserving label + created_at),
      2. repoint every obs row from old → new (now valid: new PK exists),
      3. delete the old `weeks` row (nothing references it anymore, so the
         CASCADE deletes no obs rows).

    All within the caller's single transaction. Raises ValueError if `new`
    already exists or `old` does not.
    """
    if old == new:
        return
    if not week_exists(conn, old):
        raise ValueError(f"Week {old!r} does not exist")
    if week_exists(conn, new):
        raise ValueError(f"Week {new!r} already exists")

    conn.execute(
        """
        INSERT INTO weeks (iso_week, label, created_at)
        SELECT ?, label, created_at FROM weeks WHERE iso_week = ?
        """,
        (new, old),
    )
    for crop in CROPS:
        table = _quote_ident(crop.obs_table)
        conn.execute(
            f'UPDATE {table} SET "iso_week" = ? WHERE "iso_week" = ?',
            (new, old),
        )
    conn.execute("UPDATE pest_obs SET iso_week = ? WHERE iso_week = ?", (new, old))
    conn.execute("UPDATE reactive_obs SET iso_week = ? WHERE iso_week = ?", (new, old))
    conn.execute("DELETE FROM weeks WHERE iso_week = ?", (old,))


def list_obs_for_week(
    conn: sqlite3.Connection,
    crop_code: str,
    iso_week: str,
) -> list[sqlite3.Row]:
    """All obs rows for a (crop, week), one per location_id present in the table."""
    table = _quote_ident(f"obs_{crop_code}")
    return list(conn.execute(
        f'SELECT * FROM {table} WHERE "iso_week" = ? ORDER BY "location_id"',
        (iso_week,),
    ))


# ---- Pest ID helpers -------------------------------------------------------

def clear_pest_for_week(conn: sqlite3.Connection, crop_code: str, iso_week: str) -> None:
    conn.execute(
        "DELETE FROM pest_obs WHERE crop_code = ? AND iso_week = ?",
        (crop_code, iso_week),
    )


def upsert_pest_row(
    conn: sqlite3.Connection,
    crop_code: str,
    iso_week: str,
    location_id: str,
    card_completed: bool,
    source_date: str | None,
    source_week: int | None,
    bugs_json: str,
) -> None:
    conn.execute(
        """
        INSERT INTO pest_obs
            (crop_code, iso_week, location_id, card_completed, source_date, source_week, bugs_json)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(crop_code, iso_week, location_id) DO UPDATE SET
            card_completed = excluded.card_completed,
            source_date    = excluded.source_date,
            source_week    = excluded.source_week,
            bugs_json      = excluded.bugs_json
        """,
        (crop_code, iso_week, location_id, 1 if card_completed else 0,
         source_date, source_week, bugs_json),
    )


def list_pest_for_week(
    conn: sqlite3.Connection,
    crop_code: str,
    iso_week: str,
) -> list[sqlite3.Row]:
    """All pest rows for a (crop, week), one per location that was imported."""
    return list(conn.execute(
        """
        SELECT * FROM pest_obs
        WHERE crop_code = ? AND iso_week = ?
        ORDER BY location_id
        """,
        (crop_code, iso_week),
    ))


# ---- Reactive helpers ------------------------------------------------------

def upsert_reactive_row(
    conn: sqlite3.Connection,
    crop_code: str,
    iso_week: str,
    field: str,
    when_iso: str,
    lat: float | None,
    lon: float | None,
    source_date: str | None,
    values_json: str,
) -> None:
    """Upsert one reactive point, keyed by (crop, week, field, time, coords).

    Re-importing the same event overwrites in place; a later event in the same
    week accumulates (different `when_iso`). The display ID is derived later.
    """
    conn.execute(
        """
        INSERT INTO reactive_obs
            (crop_code, iso_week, field, when_iso, lat, lon, source_date, values_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(crop_code, iso_week, field, when_iso, lat, lon) DO UPDATE SET
            source_date = excluded.source_date,
            values_json = excluded.values_json
        """,
        (crop_code, iso_week, field, when_iso, lat, lon, source_date, values_json),
    )


def list_reactive_for_week(
    conn: sqlite3.Connection,
    crop_code: str,
    iso_week: str,
) -> list[sqlite3.Row]:
    """Reactive points for a (crop, week), oldest first."""
    return list(conn.execute(
        """
        SELECT * FROM reactive_obs
        WHERE crop_code = ? AND iso_week = ?
        ORDER BY when_iso, lat, lon
        """,
        (crop_code, iso_week),
    ))


def list_reactive_all(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Every reactive point across all weeks/crops, oldest first.

    Feeds the per-field chronological numbering (F1, F2...), which spans weeks
    and both crops, so the caller needs the whole set.
    """
    return list(conn.execute(
        "SELECT * FROM reactive_obs ORDER BY when_iso, lat, lon"
    ))
