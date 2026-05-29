"""Schema classification + field-pairing characterization tests.

These pin the domain shape the client confirmed: 16 nutrients, 8 ratios,
8 canola diseases, 9 TDR readings, severity bands as a Low/Med/High picker,
and the unit-stripped `key` that all internal matching relies on.
"""
from __future__ import annotations

from app.schema import (
    FieldKind,
    classify,
    pair_disease_fields,
    pair_nutrient_fields,
    pair_ratio_fields,
    petal_test_fields,
    read_template_fields,
    tdr_fields,
)


def test_classify_basic_kinds():
    assert classify("ID") is FieldKind.KEY
    assert classify("Location") is FieldKind.LOCATION
    assert classify("Date_Time") is FieldKind.DATETIME
    assert classify("Canola_Crop_Growth_Stage") is FieldKind.GROWTH_STAGE
    assert classify("Images") is FieldKind.IMAGES


def test_classify_disease_vs_severity():
    # Severity is checked before presence.
    assert classify("Disease_Blackleg") is FieldKind.DISEASE_PRESENCE
    assert classify("Disease_Blackleg_Severity") is FieldKind.SEVERITY
    assert classify("Insect_Damage_Severity") is FieldKind.SEVERITY
    # Free-text exception in the corn template.
    assert classify("Disease_Report_Results") is FieldKind.TEXT


def test_classify_numbers_and_rates():
    assert classify("TDR_1_SOIL_TEMPERATURE") is FieldKind.NUMBER
    assert classify("N") is FieldKind.NUMBER
    assert classify("NO3N") is FieldKind.NUMBER
    assert classify("N_rate") is FieldKind.RATING
    assert classify("N/S_Actual") is FieldKind.NUMBER
    assert classify("N/S_Expected") is FieldKind.NUMBER
    assert classify("Petal_Test_Total_Infected_%") is FieldKind.NUMBER
    # Lab report numbers are free text, not numbers.
    assert classify("Petal_Test_No.") is FieldKind.TEXT
    assert classify("ReportNo") is FieldKind.TEXT


def test_field_key_strips_units(canola):
    fields = read_template_fields(canola.template_path)
    by_key = {f.key: f for f in fields}
    # The template header carries the unit; the key does not.
    assert "N" in by_key
    assert by_key["N"].name == "N (%)"
    assert "TDR_1_SOIL_TEMPERATURE" in by_key
    assert by_key["TDR_1_SOIL_TEMPERATURE"].name == "TDR_1_SOIL_TEMPERATURE (°C)"


def test_canola_domain_counts(canola):
    fields = read_template_fields(canola.template_path)

    # 16 nutrient/level pairs, 8 ratio pairs.
    assert len(pair_nutrient_fields(fields)) == 16
    assert len(pair_ratio_fields(fields)) == 8

    # 8 canola diseases, each must have a matched severity sibling.
    disease_pairs = pair_disease_fields(fields)
    assert len(disease_pairs) == 8
    assert all(sev is not None for _, sev in disease_pairs)

    # 3 sensors x 3 readings = 9 TDR fields.
    assert len(tdr_fields(fields)) == 9

    # Petal test: a free-text No. + a numeric percent.
    assert len(petal_test_fields(fields)) >= 1


def test_corn_template_loads(corn):
    # Corn has a wider template; just assert it classifies without error and
    # carries the same nutrient/ratio structure.
    fields = read_template_fields(corn.template_path)
    assert len(pair_nutrient_fields(fields)) == 16
    assert len(pair_ratio_fields(fields)) == 8
    assert len(tdr_fields(fields)) == 9
