"""Tests for the real-Survey123 scouting importer (GPS join + translation)."""
from __future__ import annotations

import pytest

from app.importers.scouting import parse_scouting_file, _parse_when
from app.schema import read_template_locations
from app.services import observations as obs_service
from app.services import scouting
from app.services import weeks as weeks_service


def _loc(crop, idx):
    return read_template_locations(crop.template_path)[idx]  # (id, lat, lon)


@pytest.mark.parametrize("raw,expect", [
    ("6/9/2026 15:57", "2026-06-09 15:57"),           # THE live format: US 24h, no secs
    ("6/9/2026 15:57:30", "2026-06-09 15:57"),        # US 24h with seconds
    ("4/15/2026 3:18:01 PM", "2026-04-15 15:18"),     # US 12h with seconds
    ("6/9/2026 4:05 PM", "2026-06-09 16:05"),         # US 12h no seconds
    ("2026-06-09 16:05:00", "2026-06-09 16:05"),      # plain ISO, space
    ("2026-06-09T16:05:00", "2026-06-09 16:05"),      # ISO with T
    ("2026-06-09T16:05:00.000Z", "2026-06-09 16:05"), # ISO + fractional + Z
    ("2026-06-09T16:05:00+00:00", "2026-06-09 16:05"),# ISO + offset
])
def test_parse_when_accepts_every_arcgis_dialect(raw, expect):
    """Survey123/ArcGIS CSVs stamp timestamps several ways — a format we don't
    accept silently drops every row and yields the 'no dated rows' error."""
    dt = _parse_when(raw)
    assert dt is not None and dt.strftime("%Y-%m-%d %H:%M") == expect


def test_parse_when_rejects_junk():
    assert _parse_when("") is None
    assert _parse_when("not a date") is None


# Header layout mirrors the real export's hazards: duplicate names with
# different meanings ("Pythium Stalk Rot" = severity col AND presence col,
# "Where are you?" twice), the double-spaced "Date &  Time", question-text
# columns, and x/y coordinates at the end.
HEADER = (
    'OBJECTID,Date &  Time,Scouters Name,Where are you?,Where are you?,'
    'Canola or Corn?,Canola Crop Growth Stage,Corn Crop Growth Stage,'
    '#1 TDR - SOIL MOISTURE,TDR Readings #1 - SOIL TEMPERATURE,'
    'TDR Reading #1 - SOIL EC,TDR Reading #2 - SOIL TEMPERATURE,'
    'Severity of Blackleg,Blackleg,Severity of Scleractinia Stem Rot,'
    'Pythium Stalk Rot,Fusarium stalk rot,Pythium Stalk Rot,'
    'Corn Disease(s),Is there evidence of insect damage?,'
    'Please name the insect(s) ,Please take pictures of the damage and describe it below,'
    'Insect Damage Severity,"""Other"" disease",Optional Additional Notes,'
    'Optional Notes,x,y'
)


def _row(when, scouter, crop, lat, lon, **kw):
    cols = {
        "objectid": "1", "when": when, "scouter": scouter,
        "where1": kw.get("where", "Field X"), "where2": "",
        "crop": crop,
        "canola_gs": kw.get("canola_gs", ""), "corn_gs": kw.get("corn_gs", ""),
        "moist1": kw.get("moist1", ""), "temp1": kw.get("temp1", ""),
        "ec1": kw.get("ec1", ""), "temp2": kw.get("temp2", ""),
        "sev_blackleg": kw.get("sev_blackleg", ""), "blackleg": kw.get("blackleg", ""),
        "sev_sclero": kw.get("sev_sclero", ""),
        "pythium_sev": kw.get("pythium_sev", ""), "fusarium": kw.get("fusarium", ""),
        "pythium_yes": kw.get("pythium_yes", ""),
        "corn_multiselect": kw.get("corn_multiselect", ""),
        "insect_evidence": kw.get("insect_evidence", ""),
        "insect_name": kw.get("insect_name", ""), "insect_desc": kw.get("insect_desc", ""),
        "insect_sev": kw.get("insect_sev", ""),
        "other_disease_text": kw.get("other_disease_text", ""),
        "notes_a": kw.get("notes_a", ""), "notes_b": kw.get("notes_b", ""),
        "x": str(lon), "y": str(lat),
    }
    return ",".join('"' + v.replace('"', '""') + '"' for v in cols.values())


def _write(tmp_path, rows):
    p = tmp_path / "scout.csv"
    p.write_text(HEADER + "\n" + "\n".join(rows) + "\n", encoding="utf-8")
    return p


@pytest.fixture
def scout_file(tmp_path, canola, corn):
    m1 = _loc(canola, 0)   # (id, lat, lon)
    m2 = _loc(canola, 1)
    l1 = _loc(corn, 0)
    rows = [
        # June 9 event — canola at M1 (jitter ~3 m), full values incl. notes
        _row("6/9/2026 4:05:19 PM", "Christina", "Canola", m1[1] + 0.00003, m1[2],
             canola_gs="10 - Cotyledons completely unfold",
             moist1="27.4", temp1="20.1", ec1="0.18", temp2="19.9",
             sev_blackleg="Medium", blackleg="Yes",
             insect_name="Flea beetle", insect_desc="chewed cotyledons",
             insect_sev="No damage",
             other_disease_text="Mystery rot",
             notes_a="even emergence", notes_b="volunteer barley"),
        # June 9 — canola at M2, sparse
        _row("6/9/2026 4:12:00 PM", "Christina", "Canola", m2[1], m2[2] + 0.00004,
             canola_gs="10 - Cotyledons completely unfold", moist1="30.1"),
        # June 9 — corn at L1: dup-name disambiguation + template-typo alias
        _row("6/9/2026 5:36:00 PM", "Cierra", "Corn", l1[1], l1[2],
             corn_gs="10 - First leaf through coleoptile",
             pythium_sev="Medium", fusarium="Yes", pythium_yes="Yes",
             insect_sev="Medium"),
        # June 9 — canola again at M1, LATER (supersedes the 4:05 row)
        _row("6/9/2026 8:05:00 PM", "Christina", "Canola", m1[1], m1[2] + 0.00002,
             canola_gs="11 - First leaf unfolded", moist1="33.8"),
        # June 9 — junk row far away (1+ km from anything)
        _row("6/9/2026 9:00:00 PM", "Christina", "Canola", m1[1] + 0.05, m1[2],
             canola_gs="10 - Cotyledons completely unfold"),
        # May 25 — old-form corn row: multiselect instead of Yes/No block
        _row("5/25/2026 5:30:00 PM", "Grayson", "Corn", l1[1], l1[2],
             corn_multiselect="Eyespot", corn_gs="09 - Emergence"),
    ]
    return _write(tmp_path, rows)


# ---- parser -----------------------------------------------------------------

def test_events_grouped_by_date(scout_file):
    parsed = parse_scouting_file(scout_file)
    assert [e.day.isoformat() for e in parsed.events] == ["2026-05-25", "2026-06-09"]
    jun9 = parsed.events[1]
    assert len(jun9.rows) == 5
    assert jun9.crop_counts == {"canola": 4, "corn": 1}
    assert jun9.scouters == ["Christina", "Cierra"]


# ---- assignment + commit ------------------------------------------------------

def test_commit_writes_both_crops_with_guarantees(isolated_db, scout_file, canola, corn):
    weeks_service.create_week("2026-W24")
    res = scouting.commit(scout_file, "2026-W24", "2026-06-09")

    assert res["imported"] == {"canola": 2, "corn": 1}   # M1, M2 + L1
    assert res["superseded"] == 1                          # the 4:05 M1 row
    assert len(res["skipped"]) == 1                        # the far-away row
    assert res["skipped"][0]["status"] == "too_far"
    assert res["skipped"][0]["dist_m"] > scouting.TOLERANCE_M
    assert res["unmapped_columns"] == []

    m1_id = _loc(canola, 0)[0]
    m1 = obs_service.load("canola", "2026-W24", m1_id)
    # latest row won: 8:05 PM values, not 4:05 PM
    assert m1["Canola_Crop_Growth_Stage"] == "11 - First leaf unfolded"
    assert m1["Date_Time"] == "2026-06-09 20:05"

    l1_id = _loc(corn, 0)[0]
    l1 = obs_service.load("corn", "2026-W24", l1_id)
    assert l1["Corn_Crop_Growth_Stage"] == "10 - First leaf through coleoptile"
    # duplicate-name disambiguation by value domain:
    assert l1["Disease_Pythium_Stalk_Rot"] == "yes"            # "Yes" column
    assert l1["Disease_Pythium_Stalk_Rot_Severity"] == "Med"   # "Medium" column
    # template-typo alias (form says Fusarium, template says Fusaruim):
    assert l1["Disease_Fusaruim_Stalk_Rot"] == "yes"
    assert l1["Insect_Damage_Severity"] == "Med"


def test_value_transforms_and_notes(isolated_db, scout_file, canola):
    weeks_service.create_week("2026-W24")
    scouting.commit(scout_file, "2026-W24", "2026-06-09")
    m2_id = _loc(canola, 1)[0]
    m2 = obs_service.load("canola", "2026-W24", m2_id)
    # The 4:05 M1 row was superseded, so check its transforms on... M2 is sparse;
    # transforms are asserted via the superseded-winner (M1) and L1 above. Here:
    assert m2["TDR_1_SOIL_MOISTURE (%)"] == "30.1"

    # The superseded M1 row's values must NOT be present (latest-wins is whole-row)
    m1 = obs_service.load("canola", "2026-W24", _loc(canola, 0)[0])
    assert m1.get("Disease_Blackleg") in (None, "")     # only in the 4:05 row
    assert m1.get("Notes") in (None, "")


def test_old_form_multiselect_fallback(isolated_db, scout_file, corn):
    weeks_service.create_week("2026-W21")
    res = scouting.commit(scout_file, "2026-W21", "2026-05-25")
    assert res["imported"] == {"corn": 1}
    l1 = obs_service.load("corn", "2026-W21", _loc(corn, 0)[0])
    assert l1["Disease_Eyespot"] == "yes"


def test_notes_and_insect_mapping(isolated_db, tmp_path, canola):
    # A single fresh row (no supersede) to assert the full text mappings.
    m1 = _loc(canola, 0)
    p = _write(tmp_path, [
        _row("6/16/2026 1:00:00 PM", "Christina", "Canola", m1[1], m1[2],
             canola_gs="12 - 2 leaves unfolded",
             sev_blackleg="High", blackleg="Yes",
             insect_name="Flea beetle", insect_desc="chewed cotyledons",
             insect_sev="Low",
             other_disease_text="Mystery rot",
             notes_a="even emergence", notes_b="volunteer barley"),
    ])
    weeks_service.create_week("2026-W25")
    scouting.commit(p, "2026-W25", "2026-06-16")
    row = obs_service.load("canola", "2026-W25", m1[0])
    assert row["Disease_Blackleg"] == "yes"
    assert row["Disease_Blackleg_Severity"] == "High"
    assert row["Insect_Identification"] == "Flea beetle"
    assert row["Insect_Damage"] == "chewed cotyledons"
    assert row["Insect_Damage_Severity"] == "Low"
    assert row["Notes"] == "even emergence; volunteer barley; Other disease: Mystery rot"


def test_raw_field_name_dialect(isolated_db, tmp_path, corn):
    """Survey123's other export dialect: underscore names truncated at ~31
    chars (Severity_of_Alternaria_Blackspo, Clubroot2, TDR_SOIL_MOISTURE...).
    """
    l1 = _loc(corn, 0)
    header = (
        "OBJECTID,esrignss_speed,Date_Time,Scouters_Name,Where_are_you,Canola_or_Corn,"
        "Corn_Crop_Growth_Stage,TDR_SOIL_MOISTURE,TDR_Reading_SOIL_EC,"
        "TDR_Readings_1_SOIL_TEMPERATURE,TDR_Reading_2_SOIL_TEMPERATURE,"
        "Severity_of_Northern_corn_bligh,Northern_corn_blight,Pythium_stalk_rot2,"
        "Corn_Diseases,Is_there_evidence_of_insect_dam,Please_name_the_insects,"
        "How_severe_is_the_damage,Optional_Additional_Notes,Other_disease,x,y"
    )
    row = (
        '1,0,6/9/2026 5:36:00 PM,Cierra,Field 17,Corn,'
        '10 - First leaf through coleoptile,32.7,0.46,18.9,18.6,'
        'Medium,Yes,Yes,'
        'Eyespot,Yes,Wireworm,'
        'Low,Weathered plants,White mold,'
        f'{l1[2]},{l1[1]}'
    )
    p = tmp_path / "raw.csv"
    p.write_text(header + "\n" + row + "\n", encoding="utf-8")

    weeks_service.create_week("2026-W26")
    res = scouting.commit(p, "2026-W26", "2026-06-09")
    assert res["imported"] == {"corn": 1}
    assert res["unmapped_columns"] == []

    out = obs_service.load("corn", "2026-W26", l1[0])
    assert out["Corn_Crop_Growth_Stage"] == "10 - First leaf through coleoptile"
    assert out["TDR_1_SOIL_MOISTURE (%)"] == "32.7"           # unnumbered raw col
    assert out["TDR_1_SOIL_EC (dS/m)"] == "0.46"
    assert out["TDR_2_SOIL_TEMPERATURE (°C)"] == "18.6"
    assert out["Disease_Northern_Corn_Blight"] == "yes"
    assert out["Disease_Northern_Corn_Blight_Severity"] == "Med"   # truncated header
    assert out["Disease_Pythium_Stalk_Rot"] == "yes"               # Clubroot2-style dedup
    assert out["Disease_Eyespot"] == "yes"                          # multiselect fallback
    assert out["Insect_Identification"] == "Wireworm"
    assert out["Insect_Damage_Severity"] == "Low"                   # How_severe fallback
    assert out["Notes"] == "Weathered plants; Other disease: White mold"


def test_prepare_preview_shape(isolated_db, scout_file):
    prep = scouting.prepare(scout_file)
    jun9 = next(e for e in prep["events"] if e["date"] == "2026-06-09")
    assert jun9["matched"] == 3
    statuses = [a["status"] for a in jun9["assignments"]]
    assert statuses.count("too_far") == 1
    sup = [a for a in jun9["assignments"] if a["superseded"]]
    assert len(sup) == 1 and sup[0]["time"] == "4:05 PM"
    ok = [a for a in jun9["assignments"] if a["status"] == "matched" and not a["superseded"]]
    assert all(a["dist_m"] <= scouting.TOLERANCE_M for a in ok)
    assert all(a["second_dist_m"] > 2 * a["dist_m"] for a in ok if a["dist_m"])
