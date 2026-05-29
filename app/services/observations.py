"""Observation service: load/save a row + the shared form *structure*.

`build_form_schema` is the key extraction. It returns a Qt-free, ordered
description of the Observations screen — the exact section layout that
`observations_tab._rebuild_form` used to compute inline. Both frontends
consume it: the Qt tab builds widgets from it; the web frontend serializes
it to JSON. This guarantees the most complex screen stays identical across
both presentations.
"""
from __future__ import annotations

from dataclasses import dataclass, field as dc_field

from app.crops import crop_by_code
from app.db import connect, list_growth_stages, load_obs_row, save_obs_row
from app.schema import (
    Field,
    FieldKind,
    pair_disease_fields,
    pair_nutrient_fields,
    pair_ratio_fields,
    petal_test_fields,
    read_template_fields,
)


# ---- Form schema dataclasses ----------------------------------------------

@dataclass
class DiseaseRow:
    label: str
    presence: Field
    severity: Field | None


@dataclass
class NutrientRow:
    value: Field
    rate: Field | None


@dataclass
class RatioRow:
    name: str
    actual: Field
    expected: Field | None


@dataclass
class TdrRow:
    sensor_label: str
    temperature: Field | None
    ec: Field | None
    moisture: Field | None


# Section kinds:
#   "form"           ordered scalar fields (label + widget)
#   "tdr_grid"       3x3 sensor grid (tdr_rows)
#   "disease_table"  disease | presence | severity (disease_rows)
#   "nutrient_table" nutrient | value | rate (nutrient_rows)
#   "ratio_table"    ratio | actual | expected (ratio_rows)
#   "images"         the Images attach widget (single field)
@dataclass
class FormSection:
    page: str                                   # "field" | "lab"
    title: str
    kind: str
    fields: list[Field] = dc_field(default_factory=list)
    disease_rows: list[DiseaseRow] = dc_field(default_factory=list)
    nutrient_rows: list[NutrientRow] = dc_field(default_factory=list)
    ratio_rows: list[RatioRow] = dc_field(default_factory=list)
    tdr_rows: list[TdrRow] = dc_field(default_factory=list)


@dataclass
class FormSchema:
    crop_code: str
    growth_stages: list[tuple[str, str]]
    sections: list[FormSection]


def build_form_schema(crop_code: str) -> FormSchema:
    """Return the ordered, UI-agnostic structure of the Observations screen.

    Section order + inclusion rules mirror the original Qt `_rebuild_form`
    exactly:

    Field page: Observation header → Soil (TDR) → Diseases → Insects →
                Petal test (canola only) → Photos (if Images present).
    Lab page:   Report identifiers → Nutrient panel → Nutrient ratios.
    """
    crop = crop_by_code(crop_code)
    fields = read_template_fields(crop.template_path)
    by_name = {f.name: f for f in fields}
    by_key = {f.key: f for f in fields}

    with connect() as conn:
        growth_stages = [
            (r["code"], r["description"]) for r in list_growth_stages(conn, crop_code)
        ]

    sections: list[FormSection] = []

    # --- FIELD PAGE --------------------------------------------------------

    # Observation header: Date_Time + every growth-stage field.
    header_fields: list[Field] = []
    if "Date_Time" in by_name:
        header_fields.append(by_name["Date_Time"])
    header_fields.extend(f for f in fields if f.kind == FieldKind.GROWTH_STAGE)
    sections.append(FormSection("field", "Observation header", "form", fields=header_fields))

    # Soil readings (TDR): 3 sensors x (TEMPERATURE, EC, MOISTURE).
    tdr_rows: list[TdrRow] = []
    for sensor_idx in (1, 2, 3):
        tdr_rows.append(TdrRow(
            sensor_label=f"TDR {sensor_idx}",
            temperature=by_key.get(f"TDR_{sensor_idx}_SOIL_TEMPERATURE"),
            ec=by_key.get(f"TDR_{sensor_idx}_SOIL_EC"),
            moisture=by_key.get(f"TDR_{sensor_idx}_SOIL_MOISTURE"),
        ))
    sections.append(FormSection("field", "Soil readings (TDR)", "tdr_grid", tdr_rows=tdr_rows))

    # Diseases.
    disease_rows = [
        DiseaseRow(label=_disease_display(presence.name), presence=presence, severity=severity)
        for presence, severity in pair_disease_fields(fields)
    ]
    sections.append(FormSection("field", "Diseases", "disease_table", disease_rows=disease_rows))

    # Insects.
    insect_fields = [
        by_name[name]
        for name in ("Insect_Damage", "Insect_Damage_Severity", "Insect_Identification")
        if name in by_name
    ]
    sections.append(FormSection("field", "Insects", "form", fields=insect_fields))

    # Petal test (canola only — present iff the template has petal fields).
    petal = petal_test_fields(fields)
    if petal:
        sections.append(FormSection("field", "Petal test", "form", fields=list(petal)))

    # Photos.
    if "Images" in by_name:
        sections.append(FormSection("field", "Photos", "images", fields=[by_name["Images"]]))

    # --- LAB PAGE ----------------------------------------------------------

    report_fields = [
        by_name[name]
        for name in ("ReportNo", "Lab_No.", "Disease_Report_Results")
        if name in by_name
    ]
    sections.append(FormSection("lab", "Report identifiers", "form", fields=report_fields))

    nutrient_rows = [
        NutrientRow(value=val_f, rate=rate_f)
        for val_f, rate_f in pair_nutrient_fields(fields)
    ]
    sections.append(FormSection("lab", "Nutrient panel", "nutrient_table", nutrient_rows=nutrient_rows))

    ratio_rows = [
        RatioRow(name=name, actual=actual, expected=expected)
        for name, actual, expected in pair_ratio_fields(fields)
    ]
    sections.append(FormSection("lab", "Nutrient ratios", "ratio_table", ratio_rows=ratio_rows))

    return FormSchema(crop_code=crop_code, growth_stages=growth_stages, sections=sections)


def _disease_display(name: str) -> str:
    """Strip the `Disease_` prefix for the table label (matches the old UI)."""
    return name.removeprefix("Disease_").replace("_", " ")


# ---- Load / save ----------------------------------------------------------

def load(crop_code: str, iso_week: str, location_id: str) -> dict[str, str]:
    with connect() as conn:
        return load_obs_row(conn, crop_code, iso_week, location_id)


def save(crop_code: str, iso_week: str, location_id: str, values: dict[str, str]) -> None:
    with connect() as conn:
        save_obs_row(conn, crop_code, iso_week, location_id, values)
