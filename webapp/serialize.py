"""JSON serialization for service-layer dataclasses.

The services return rich dataclasses (Field, FormSchema, WeekStatus, ...).
This module is the ONLY place that knows how to flatten them into plain
JSON-able dicts for the web frontend. Keeping it separate means the services
stay UI-agnostic and the route handlers stay tiny.
"""
from __future__ import annotations

from app.importers.core import LoadedFile
from app.schema import Field
from app.services.exports import ExportResult, WeekStatus
from app.services.imports import ImportResult
from app.services.observations import (
    DiseaseRow,
    FormSchema,
    FormSection,
    NutrientRow,
    RatioRow,
    TdrRow,
)


# ---- Form schema -----------------------------------------------------------

def field_dict(f: Field | None) -> dict | None:
    """A template field flattened to what a form input needs to render."""
    if f is None:
        return None
    return {
        "name": f.name,          # exact header = DB column = form key
        "key": f.key,            # unit-free label
        "kind": f.kind.value,    # drives the input widget type
        "choices": list(f.choices),
    }


def _disease_row(row: DiseaseRow) -> dict:
    return {
        "label": row.label,
        "presence": field_dict(row.presence),
        "severity": field_dict(row.severity),
    }


def _nutrient_row(row: NutrientRow) -> dict:
    return {"value": field_dict(row.value), "rate": field_dict(row.rate)}


def _ratio_row(row: RatioRow) -> dict:
    return {
        "name": row.name,
        "actual": field_dict(row.actual),
        "expected": field_dict(row.expected),
    }


def _tdr_row(row: TdrRow) -> dict:
    return {
        "sensor_label": row.sensor_label,
        "temperature": field_dict(row.temperature),
        "ec": field_dict(row.ec),
        "moisture": field_dict(row.moisture),
    }


def section_dict(s: FormSection) -> dict:
    return {
        "page": s.page,
        "title": s.title,
        "kind": s.kind,
        "fields": [field_dict(f) for f in s.fields],
        "disease_rows": [_disease_row(r) for r in s.disease_rows],
        "nutrient_rows": [_nutrient_row(r) for r in s.nutrient_rows],
        "ratio_rows": [_ratio_row(r) for r in s.ratio_rows],
        "tdr_rows": [_tdr_row(r) for r in s.tdr_rows],
    }


def form_schema_dict(schema: FormSchema) -> dict:
    return {
        "crop_code": schema.crop_code,
        "growth_stages": [
            {"code": code, "description": desc} for code, desc in schema.growth_stages
        ],
        "sections": [section_dict(s) for s in schema.sections],
    }


# ---- Status / results ------------------------------------------------------

def week_status_dict(status: WeekStatus) -> dict:
    return {
        "expected_fields": status.expected_fields,
        "locations_with_data": status.locations_with_data,
        "total_locations": status.total_locations,
        "locations": [
            {
                "location_id": loc.location_id,
                "lat": loc.lat,
                "lon": loc.lon,
                "filled": loc.filled,
            }
            for loc in status.locations
        ],
    }


def import_result_dict(res: ImportResult) -> dict:
    return {
        "imported": res.imported,
        "skipped_no_loc": res.skipped_no_loc,
        "skipped_no_target": res.skipped_no_target,
        "skipped_empty": res.skipped_empty,
        "photos_copied": res.photos_copied,
        "photos_missing": res.photos_missing,
        "warnings": list(res.warnings),
    }


def export_result_dict(res: ExportResult) -> dict:
    return {
        "week": res.week,
        "produced": [p.name for p in res.produced],
        "errors": [{"crop": crop, "message": msg} for crop, msg in res.errors],
        "zip_name": res.zip_path.name if res.zip_path else None,
    }


# ---- Import preview --------------------------------------------------------

def mapping_dict(loaded: LoadedFile) -> dict:
    """The auto-mapping summary the import screens show after upload."""
    m = loaded.mapping
    return {
        "matches": dict(m.matches),
        "unmatched_source": list(m.unmatched_source),
        "unmatched_target": list(m.unmatched_target),
    }


def loaded_preview_dict(loaded: LoadedFile, max_rows: int = 200) -> dict:
    """Source columns, the mapping, and a capped slice of rows for preview."""
    return {
        "row_count": loaded.row_count,
        "source_cols": list(loaded.source_cols),
        "mapping": mapping_dict(loaded),
        "rows": [dict(r) for r in loaded.rows[:max_rows]],
    }
