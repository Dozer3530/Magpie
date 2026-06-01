"""Week-over-week trend service.

The same fixed monitoring points are measured every week, so the interesting
signal is *change over time*. `soil_trends` returns the TDR soil readings —
temperature, moisture, EC — as one value per week, either as the field average
(mean across all points) or for a single monitoring point.

Values are the mean of that point's three TDR sensors; the field average is the
mean of those per-point means. Weeks are ordered chronologically (by the week
row's `created_at`, so it works even after a week's code is renamed). A week
with no data for the metric yields `None` (a gap in the series).
"""
from __future__ import annotations

from statistics import mean

from app.crops import crop_by_code
from app.db import connect, list_locations, list_obs_for_week, list_weeks
from app.schema import read_template_fields

# metric key, display label, unit, the TDR_<i>_<suffix> these average over.
_METRICS = [
    ("temp", "Soil temp", "°C", "SOIL_TEMPERATURE"),
    ("moisture", "Soil moisture", "%", "SOIL_MOISTURE"),
    ("ec", "Soil EC", "dS/m", "SOIL_EC"),
]


def _num(v) -> float | None:
    if v in (None, ""):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def soil_trends(crop_code: str, location_id: str | None = None) -> dict:
    """Week-ordered temp/moisture/EC series for a crop.

    location_id=None → field average across all points; otherwise that point.
    """
    crop = crop_by_code(crop_code)
    fields = read_template_fields(crop.template_path)
    by_key = {f.key: f for f in fields}

    # metric -> the actual column names of its 1..3 sensors present in the template
    metric_cols: dict[str, list[str]] = {}
    for mkey, _label, _unit, suffix in _METRICS:
        cols = [by_key[f"TDR_{i}_{suffix}"].name for i in (1, 2, 3) if f"TDR_{i}_{suffix}" in by_key]
        metric_cols[mkey] = cols

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

    def point_mean(row: dict, cols: list[str]) -> float | None:
        vals = [v for v in (_num(row.get(c)) for c in cols) if v is not None]
        return mean(vals) if vals else None

    series: dict[str, dict] = {}
    for mkey, label, unit, _suffix in _METRICS:
        cols = metric_cols[mkey]
        points: list[float | None] = []
        for wt in week_tags:
            obs = per_week[wt]
            if location_id is not None:
                pm = point_mean(obs.get(location_id, {}), cols)
                points.append(round(pm, 1) if pm is not None else None)
            else:
                loc_means = [m for m in (point_mean(obs.get(lid, {}), cols) for lid in locs) if m is not None]
                points.append(round(mean(loc_means), 1) if loc_means else None)
        series[mkey] = {"label": label, "unit": unit, "points": points}

    return {
        "crop": crop_code,
        "scope": location_id or "field",
        "locations": locs,
        "weeks": week_tags,
        "series": series,
    }
