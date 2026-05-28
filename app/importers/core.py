"""Shared import logic for Survey123 and lab files.

Both importers do roughly the same thing:

  1. Load a CSV/XLSX into a list of dict rows (string-valued).
  2. Auto-map source column names to the active crop's template field names.
  3. Save mapped values into `obs_<crop>` rows.

They differ only in how a source row maps to a location:

  - Survey123: source has an "ID" column with values like M1, M2, ... — auto-join.
  - Lab:       user picks a target location per source row in the UI.

Conflict policy is **overwrite**: any non-empty source value wins over what's
already in the obs row. Blank source cells are skipped (they don't clobber
existing data with empty strings).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from app.schema import Field, read_template_fields


# ---- Load ------------------------------------------------------------------

def load_table(path: Path) -> list[dict[str, str]]:
    """Read CSV or XLSX into list-of-dicts with string values.

    Pandas does most of the work; we just coerce every cell to a clean string
    (NaN/None → ''), trim whitespace, and preserve the original column order
    via the `_columns` first-row sentinel returned alongside.
    """
    path = Path(path)
    ext = path.suffix.lower()
    if ext == ".csv":
        df = pd.read_csv(path, dtype=str, keep_default_na=False)
    elif ext in (".xlsx", ".xlsm", ".xls", ".xlsb", ".ods"):
        # `calamine` reads both modern xlsx and legacy xls (the format the
        # PT2R lab still emits). It's also faster than openpyxl/xlrd.
        df = pd.read_excel(path, dtype=str, engine="calamine")
    else:
        raise ValueError(f"Unsupported file type: {path.suffix}")

    # Normalize: strip whitespace from column names and cell values.
    df.columns = [str(c).strip() for c in df.columns]
    rows: list[dict[str, str]] = []
    for _, row in df.iterrows():
        out: dict[str, str] = {}
        for col, val in row.items():
            if val is None or (isinstance(val, float) and math.isnan(val)):
                out[col] = ""
            else:
                out[col] = str(val).strip()
        rows.append(out)
    return rows


def source_columns(rows: list[dict[str, str]]) -> list[str]:
    """Return the source column names in dict-insertion order."""
    if not rows:
        return []
    return list(rows[0].keys())


# ---- Column mapping --------------------------------------------------------

@dataclass
class ColumnMapping:
    """Auto-derived mapping between source columns and template fields."""
    # source column name -> target template field name (only when matched)
    matches: dict[str, str] = field(default_factory=dict)
    # source columns with no template match (ignored on import)
    unmatched_source: list[str] = field(default_factory=list)
    # template fields with no source column (left untouched on import)
    unmatched_target: list[str] = field(default_factory=list)


def _normalize(name: str) -> str:
    return name.strip().lower().replace(" ", "_")


def auto_map_columns(
    source_cols: list[str],
    template_fields: list[Field],
) -> ColumnMapping:
    """Match by exact header text, falling back to case/whitespace-insensitive.

    The template is authoritative — its column names are the targets.
    Source columns that don't match a template field are reported but not
    used on import.
    """
    target_by_exact = {f.name: f.name for f in template_fields}
    target_by_norm = {_normalize(f.name): f.name for f in template_fields}
    # Match against the unit-free key too, so a lab column "N" maps to the
    # template's unit-bearing header "N (%)".
    target_by_key = {_normalize(f.key): f.name for f in template_fields}

    matches: dict[str, str] = {}
    unmatched_source: list[str] = []
    matched_target: set[str] = set()

    for col in source_cols:
        if col in target_by_exact:
            tgt = target_by_exact[col]
        else:
            norm = _normalize(col)
            tgt = target_by_norm.get(norm) or target_by_key.get(norm)
        if tgt is None:
            unmatched_source.append(col)
        else:
            matches[col] = tgt
            matched_target.add(tgt)

    unmatched_target = [f.name for f in template_fields if f.name not in matched_target]
    return ColumnMapping(
        matches=matches,
        unmatched_source=unmatched_source,
        unmatched_target=unmatched_target,
    )


# ---- Apply mapping to a row -----------------------------------------------

# Columns we never want to write — they're either PK metadata or replaced
# by the locations table at export time.
_NEVER_WRITE = {"ID", "Location"}


def project_row(row: dict[str, str], mapping: ColumnMapping) -> dict[str, str]:
    """Return the row keyed by *template* column names, only mapped values.

    Drops blank source cells so import doesn't blank out existing data
    (overwrite-on-write only applies to non-empty cells).
    Skips PK / location columns — those are handled by the caller.
    """
    out: dict[str, str] = {}
    for src_col, tgt_col in mapping.matches.items():
        if tgt_col in _NEVER_WRITE:
            continue
        val = row.get(src_col, "")
        if val == "":
            continue
        out[tgt_col] = val
    return out


# ---- Convenience: load + map in one shot ----------------------------------

@dataclass
class LoadedFile:
    path: Path
    rows: list[dict[str, str]]
    source_cols: list[str]
    mapping: ColumnMapping

    @property
    def row_count(self) -> int:
        return len(self.rows)


def load_for_crop(path: Path, crop_template_path: Path) -> LoadedFile:
    rows = load_table(path)
    fields = read_template_fields(crop_template_path)
    cols = source_columns(rows)
    mapping = auto_map_columns(cols, fields)
    return LoadedFile(path=Path(path), rows=rows, source_cols=cols, mapping=mapping)
