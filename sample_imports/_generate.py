"""Generate fake — but realistically shaped — import files for testing Magpie.

Run:  python sample_imports/_generate.py

Produces, for each crop, into this folder:
  <crop>_survey123_<week>.csv   field feed: ID/Location/Date_Time/growth/TDR/
                                disease+severity/insects/petal/Images
  <crop>_lab_PT2R_<week>.csv    lab feed: SampleID/ReportDate + nutrients/
                                rates/ratios/report identifiers

Column names are taken verbatim from each `Static <Crop> Template.xlsx` row 1,
so Magpie's importer matches them by exact name (no manual mapping needed).
The values are random but plausible. Nothing here touches the database — these
are just input files you upload through the Survey123 / Lab import screens.

NOTE: the Location column carries the templates' REAL monitoring-point
coordinates, so the generated CSVs are git-ignored. Don't commit them.
"""
from __future__ import annotations

import csv
import random
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(REPO))

from app.crops import CROPS  # noqa: E402
from app.schema import (  # noqa: E402
    FieldKind,
    page_of,
    pair_disease_fields,
    read_template_fields,
    read_template_locations,
)

RNG = random.Random(20260529)
WEEK = "2026-W22"


def is_lab_field(f) -> bool:
    """True if this column comes from the lab report, not the field tablet."""
    return page_of(f) == "lab"


def num_value(f) -> str:
    k = f.key
    if k.endswith("_SOIL_TEMPERATURE"):
        return f"{RNG.uniform(11, 21):.1f}"
    if k.endswith("_SOIL_EC"):
        return f"{RNG.uniform(0.2, 0.8):.2f}"
    if k.endswith("_SOIL_MOISTURE"):
        return f"{RNG.uniform(14, 42):.0f}"
    if k.startswith("Petal_Test_"):
        return f"{RNG.randint(0, 25)}"
    if k.endswith("_Actual") or k.endswith("_Expected"):
        return f"{RNG.uniform(0.3, 12):.2f}"
    if "(ppm)" in f.name or f.name.endswith("(ppm)"):
        return f"{RNG.uniform(3, 120):.0f}"
    return f"{RNG.uniform(0.05, 5):.2f}"


def text_value(f) -> str:
    name = f.name
    if name == "Insect_Damage":
        return RNG.choice(["minor leaf notching", "stem boring", "none observed", "pod feeding"])
    if name == "Insect_Identification":
        return RNG.choice(["flea beetle", "lygus bug", "diamondback moth", "aphid", ""])
    if name == "ReportNo":
        return f"R{RNG.randint(10000, 99999)}"
    if name == "Lab_No.":
        return f"PT2R-{RNG.randint(1000, 9999)}"
    if name == "Disease_Report_Results":
        return RNG.choice(["none detected", "trace fungal", "see notes", ""])
    return ""


def cell(f, *, want_disease: bool) -> str:
    kind = f.kind
    if kind == FieldKind.DATETIME:
        return f"2026-05-{RNG.randint(20, 27):02d} {RNG.randint(7, 17):02d}:{RNG.choice(['00','15','30','45'])}"
    if kind == FieldKind.GROWTH_STAGE:
        return ""  # filled by caller (needs crop stage list)
    if kind == FieldKind.DISEASE_PRESENCE:
        return "yes" if want_disease else ""
    if kind == FieldKind.SEVERITY:
        return ""  # filled by caller, paired with presence
    if kind == FieldKind.NUMBER:
        return num_value(f)
    if kind == FieldKind.RATING:
        return RNG.choice(["D", "L", "S", "H", "VH"])
    if kind == FieldKind.TEXT:
        return text_value(f)
    if kind == FieldKind.IMAGES:
        return ""
    return ""


def write_csv(path: Path, headers: list[str], rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=headers)
        w.writeheader()
        for r in rows:
            w.writerow({h: r.get(h, "") for h in headers})
    print(f"  wrote {path.relative_to(REPO)}  ({len(rows)} rows, {len(headers)} cols)")


def generate_for_crop(crop) -> None:
    fields = read_template_fields(crop.template_path)
    locations = read_template_locations(crop.template_path)
    stages = crop.growth_stages()
    disease_pairs = pair_disease_fields(fields)

    by_name = {f.name: f for f in fields}
    field_cols = [f for f in fields if f.name not in ("ID", "Location") and not is_lab_field(f)]
    lab_cols = [f for f in fields if is_lab_field(f)]

    print(f"{crop.display_name}: {len(field_cols)} field cols, {len(lab_cols)} lab cols, {len(locations)} locations")

    # ---- Survey123 (field) feed -------------------------------------------
    survey_headers = ["ID", "Location"] + [f.name for f in field_cols]
    survey_rows: list[dict] = []
    for i, (loc_id, lat, lon) in enumerate(locations):
        # spread: ~1/3 of points carry a disease flag this week
        flagged = (i % 3 == 0)
        row = {"ID": loc_id, "Location": f"{lat}, {lon}"}
        for f in field_cols:
            if f.kind == FieldKind.GROWTH_STAGE:
                code, desc = RNG.choice(stages)
                row[f.name] = f"{code} - {desc}"
            else:
                want = (f.kind == FieldKind.DISEASE_PRESENCE and flagged and RNG.random() < 0.6)
                row[f.name] = cell(f, want_disease=want)
        # pair severities to whatever presences we set to "yes"
        for presence, severity in disease_pairs:
            if severity and row.get(presence.name) == "yes":
                row[severity.name] = RNG.choice(["Low", "Med", "High"])
        # insect severity follows insect damage text being non-empty
        if "Insect_Damage_Severity" in by_name and row.get("Insect_Damage"):
            if row["Insect_Damage"] not in ("none observed", ""):
                row["Insect_Damage_Severity"] = RNG.choice(["Low", "Med", "High"])
        survey_rows.append(row)
    write_csv(HERE / f"{crop.code}_survey123_{WEEK}.csv", survey_headers, survey_rows)

    # ---- Lab (PT2R) feed --------------------------------------------------
    # Real lab files key on a SampleID, not the monitoring-point ID — so the
    # importer's per-row "assign to location" step gets exercised. We print the
    # location id in SampleID so it's easy to assign while testing.
    lab_headers = ["SampleID", "ReportDate"] + [f.name for f in lab_cols]
    lab_rows: list[dict] = []
    for i, (loc_id, _lat, _lon) in enumerate(locations):
        # leave a couple of points without lab data (realistic: not every
        # sample comes back) — skip 2 of 9
        if i in (7, 8):
            continue
        row = {
            "SampleID": f"{crop.code[:2].upper()}-{loc_id}",
            "ReportDate": f"2026-05-{RNG.randint(20, 27):02d}",
        }
        for f in lab_cols:
            row[f.name] = cell(f, want_disease=False)
        lab_rows.append(row)
    write_csv(HERE / f"{crop.code}_lab_PT2R_{WEEK}.csv", lab_headers, lab_rows)


def main() -> None:
    print(f"Generating fake import CSVs for week {WEEK} into {HERE.relative_to(REPO)}/\n")
    for crop in CROPS:
        generate_for_crop(crop)
    print("\nDone. Upload these through the Survey123 / Lab import screens to test the pipeline.")


if __name__ == "__main__":
    main()
