"""Parser for the Pest ID feed (a living per-field bug log).

These CSVs are shaped differently from the Survey123 / PT2R feeds, so they get
a dedicated parser rather than the generic column auto-mapper:

    col 0  Identification person name
    col 1  DATE                     e.g. "June 15"
    col 2  ID Number                "<point>_<weekIndex>"  e.g. "M1_3", "L9_8"
    col 3  CARD COMPLETED           "TRUE" / "FALSE"
    col 4+ one column per bug type  (variable; header row names them, counts below)

The point prefix tells us the crop (M -> canola, L -> corn). The trailing
`_<n>` on the ID is the *week index* (1..N): the sheet accumulates every week,
and on import the user picks which week to extract for the current package.
"""
from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field as dc_field
from pathlib import Path

_ID_RE = re.compile(r"^\s*([A-Za-z]+\d+)_(\d+)\s*$")
_PREFIX_RE = re.compile(r"^\s*([A-Za-z]+)\d+_\d+\s*$")

# Point-id prefix -> crop code. Mirrors app/crops.py location_prefix.
_CROP_BY_PREFIX = {"M": "canola", "L": "corn"}


@dataclass
class PestPoint:
    location_id: str
    card_completed: bool
    bugs: dict[str, str]   # bug name -> raw count (non-blank only)
    date: str


@dataclass
class WeekSlice:
    index: int
    date: str
    points: dict[str, PestPoint] = dc_field(default_factory=dict)  # location_id -> point

    @property
    def cards_completed(self) -> int:
        return sum(1 for p in self.points.values() if p.card_completed)

    @property
    def bug_types_present(self) -> list[str]:
        seen: list[str] = []
        for p in self.points.values():
            for b in p.bugs:
                if b not in seen:
                    seen.append(b)
        return seen


@dataclass
class ParsedPest:
    path: Path
    crop_code: str
    bug_names: list[str]                # every bug column in the sheet header
    weeks: list[WeekSlice]              # ordered by week index

    def week(self, index: int) -> WeekSlice | None:
        for w in self.weeks:
            if w.index == index:
                return w
        return None


def _read_rows(path: Path) -> list[list[str]]:
    # utf-8-sig drops a BOM if present; the quoted multiline header parses fine.
    with open(path, "r", encoding="utf-8-sig", newline="") as fh:
        return [row for row in csv.reader(fh)]


def parse_pest_file(path) -> ParsedPest:
    path = Path(path)
    rows = _read_rows(path)
    if not rows:
        raise ValueError("Pest file is empty.")

    header = rows[0]
    # Bug columns are everything past the 4 fixed columns, with a non-blank name.
    bug_names = [c.strip() for c in header[4:] if c.strip()]

    weeks: dict[int, WeekSlice] = {}
    crop_code: str | None = None

    for row in rows[1:]:
        if len(row) < 3:
            continue
        id_cell = (row[2] or "").strip()
        m = _ID_RE.match(id_cell)
        if not m:
            continue  # blank/filler rows
        location_id, week_index = m.group(1), int(m.group(2))

        pm = _PREFIX_RE.match(id_cell)
        prefix = pm.group(1)[:1].upper() if pm else ""
        crop = _CROP_BY_PREFIX.get(prefix)
        if crop is None:
            raise ValueError(f"Unknown point prefix in ID '{id_cell}' (expected M… or L…).")
        if crop_code is None:
            crop_code = crop
        elif crop_code != crop:
            raise ValueError("Pest file mixes Canola (M) and Corn (L) points — one field per file.")

        card = (row[3].strip().upper() == "TRUE") if len(row) > 3 else False
        date = (row[1] or "").strip()
        bugs: dict[str, str] = {}
        for i, name in enumerate(bug_names):
            col = 4 + i
            if col < len(row):
                val = (row[col] or "").strip()
                if val:
                    bugs[name] = val

        wk = weeks.setdefault(week_index, WeekSlice(index=week_index, date=date))
        if not wk.date:
            wk.date = date
        wk.points[location_id] = PestPoint(
            location_id=location_id, card_completed=card, bugs=bugs, date=date
        )

    if crop_code is None:
        raise ValueError("No valid pest rows found (expected IDs like 'M1_3' / 'L9_8').")

    ordered = [weeks[k] for k in sorted(weeks)]
    return ParsedPest(path=path, crop_code=crop_code, bug_names=bug_names, weeks=ordered)
