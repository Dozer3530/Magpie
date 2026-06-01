"""Week-over-week trend service.

The same fixed monitoring points are measured every week, so the interesting
signal is *change over time*. `trend_series` returns one value per week for a
chosen metric category, either as the field average (across all points) or for
a single point. Weeks are ordered chronologically (by the week row's
`created_at`, so it survives a week being renamed); a week with no data for a
metric yields `None` (a gap in the series).

Categories:
  soil            temp / moisture / EC (mean of a point's 3 TDR sensors)
  disease_growth  disease flags (count) + growth stage (BBCH number)
  nutrients       every bare lab nutrient value (N, P, K, ... ppm/%)
  ratios          every nutrient ratio's Actual value (N/S, K/Mg, ...)

Per-point value is that point's reading; the field value aggregates across the
points that reported that week — "mean" for readings, "sum" for disease flags
(so it reads as total pressure across the field).
"""
from __future__ import annotations

import re
from statistics import mean

from app.crops import crop_by_code
from app.db import connect, list_locations, list_obs_for_week, list_weeks
from app.schema import FieldKind, page_of, read_template_fields

CATEGORIES = ("soil", "disease_growth", "nutrients", "ratios")
CATEGORY_LABELS = {
    "soil": "Soil readings",
    "disease_growth": "Disease & growth",
    "nutrients": "Nutrient values",
    "ratios": "Nutrient ratios",
}


def _num(v) -> float | None:
    if v in (None, ""):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _bbch(v) -> float | None:
    if not v:
        return None
    m = re.match(r"\s*(\d+)", str(v))
    return float(m.group(1)) if m else None


def _agg(vals, how: str) -> float | None:
    vals = [v for v in vals if v is not None]
    if not vals:
        return None
    return mean(vals) if how == "mean" else float(sum(vals))


def _unit_in(name: str) -> str:
    if "(" in name and ")" in name:
        return name[name.find("(") + 1 : name.find(")")]
    return ""


def _specs(category: str, fields):
    """List of (key, label, unit, field_agg, value_fn(row)->float|None)."""
    by_key = {f.key: f for f in fields}
    specs = []
    if category == "soil":
        for key, label, unit, suffix in [
            ("temp", "Soil temp", "°C", "SOIL_TEMPERATURE"),
            ("moisture", "Soil moisture", "%", "SOIL_MOISTURE"),
            ("ec", "Soil EC", "dS/m", "SOIL_EC"),
        ]:
            cols = [by_key[f"TDR_{i}_{suffix}"].name for i in (1, 2, 3) if f"TDR_{i}_{suffix}" in by_key]
            specs.append((key, label, unit, "mean",
                          lambda row, cols=cols: _agg([_num(row.get(c)) for c in cols], "mean")))
    elif category == "disease_growth":
        presence = [f.name for f in fields if f.kind == FieldKind.DISEASE_PRESENCE]
        if presence:
            specs.append(("disease", "Disease flags", "", "sum",
                          lambda row, presence=presence: float(
                              sum(1 for n in presence if str(row.get(n) or "").strip().lower() == "yes"))))
        growth = [f.name for f in fields if f.kind == FieldKind.GROWTH_STAGE]
        if growth:
            specs.append(("growth", "Growth stage", "BBCH", "mean",
                          lambda row, g=growth[0]: _bbch(row.get(g))))
    elif category == "nutrients":
        for f in fields:
            if (f.kind == FieldKind.NUMBER and page_of(f) == "lab"
                    and not (f.key.endswith("_Actual") or f.key.endswith("_Expected"))):
                specs.append((f.key, f.key, _unit_in(f.name), "mean",
                              lambda row, n=f.name: _num(row.get(n))))
    elif category == "ratios":
        for f in fields:
            if f.key.endswith("_Actual"):
                base = f.key[: -len("_Actual")]
                specs.append((base, base, "", "mean",
                              lambda row, n=f.name: _num(row.get(n))))
    return specs


def trend_series(crop_code: str, location_id: str | None = None, category: str = "soil") -> dict:
    """Week-ordered series for one metric category (see module docstring)."""
    if category not in CATEGORIES:
        category = "soil"
    crop = crop_by_code(crop_code)
    fields = read_template_fields(crop.template_path)
    specs = _specs(category, fields)

    with connect() as conn:
        weeks = [dict(r) for r in list_weeks(conn)]
        locs = [r["location_id"] for r in list_locations(conn, crop_code)]
        weeks.sort(key=lambda w: (w.get("created_at") or "", w["iso_week"]))
        per_week = {
            w["iso_week"]: {
                row["location_id"]: dict(row)
                for row in list_obs_for_week(conn, crop_code, w["iso_week"])
            }
            for w in weeks
        }

    week_tags = [w["iso_week"] for w in weeks]
    series = []
    for key, label, unit, how, fn in specs:
        points = []
        for wt in week_tags:
            rows = per_week[wt]
            if location_id is not None:
                row = rows.get(location_id)
                v = fn(row) if row is not None else None
            else:
                v = _agg([fn(r) for r in rows.values()], how)
            points.append(round(v, 1) if v is not None else None)
        series.append({"key": key, "label": label, "unit": unit, "points": points})

    return {
        "crop": crop_code,
        "scope": location_id or "field",
        "category": category,
        "categories": [{"key": c, "label": CATEGORY_LABELS[c]} for c in CATEGORIES],
        "locations": locs,
        "weeks": week_tags,
        "series": series,
    }


def soil_trends(crop_code: str, location_id: str | None = None) -> dict:
    """Back-compat alias for the soil category."""
    return trend_series(crop_code, location_id, "soil")
