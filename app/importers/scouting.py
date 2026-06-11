"""Parser + translation layer for the real Survey123 scouting export.

The live form ("Scouting Point" layer CSV) looks nothing like the templates:

  - rows carry NO point IDs — only GPS (`x`/`y`, sometimes Latitude/Longitude);
  - one cumulative file holds every date and BOTH crops (`Canola or Corn?`);
  - column names are question text (`TDR Readings #1 - SOIL TEMPERATURE`,
    per-disease `Blackleg` = Yes/No, `Severity of Blackleg` = Low/Medium/High);
  - headers repeat with different meanings (`Pythium Stalk Rot` is both a
    severity column and a Yes/No column; `Where are you?` appears twice), so
    rows are kept as (header, value) PAIRS, never collapsed into a dict;
  - sloppy text: `Date &  Time` (double space), trailing spaces, the form typo
    "Scleractinia" and the template typo "Fusaruim" (explicit aliases below).

This module is pure file-parsing + per-row translation; the GPS join to
monitoring points lives in `app/services/scouting.py`.
"""
from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field as dc_field
from datetime import date, datetime
from pathlib import Path

from app.crops import CROPS
from app.schema import Field, FieldKind, read_template_fields

# Crop answer in the form -> crop code.
CROP_BY_ANSWER = {"canola": "canola", "corn": "corn"}

# The export interleaves EVERY crop's disease columns in each row (a canola row
# still carries the corn questions, blank or "No"). Each crop's translator only
# writes its own diseases; names belonging to any OTHER crop are recognized via
# this union so they're skipped silently instead of reported as unmapped.
_ALL_DISEASE_NORMS: set[str] | None = None


def _all_disease_norms() -> set[str]:
    global _ALL_DISEASE_NORMS
    if _ALL_DISEASE_NORMS is None:
        norms: set[str] = set()
        for crop in CROPS:
            for f in read_template_fields(crop.template_path):
                if f.kind == FieldKind.DISEASE_PRESENCE:
                    norms.add(_letters(_dnorm(f.key.removeprefix("Disease_"))))
                elif f.kind == FieldKind.SEVERITY and f.key != "Insect_Damage_Severity":
                    norms.add(_letters(_dnorm(f.key.removeprefix("Disease_").removesuffix("_Severity"))))
        _ALL_DISEASE_NORMS = norms
    return _ALL_DISEASE_NORMS


def _is_any_crop_disease(header: str) -> bool:
    """Does this header name a disease of ANY crop (incl. truncated raw names)?"""
    from_h, _ = _strip_severity_affixes(header)
    d = _dnorm(from_h)
    key = _letters(_DISEASE_ALIASES.get(d, d))
    if not key:
        return False
    norms = _all_disease_norms()
    if key in norms:
        return True
    return len(key) >= 10 and any(k.startswith(key) for k in norms)

# The live export stamps US M/D/YYYY in 24-HOUR time with no seconds
# ("6/9/2026 15:57") — list that first; the 12-hour AM/PM and ISO spellings
# show up in other Survey123 configurations.
_DATE_FORMATS = (
    "%m/%d/%Y %H:%M", "%m/%d/%Y %H:%M:%S",
    "%m/%d/%Y %I:%M:%S %p", "%m/%d/%Y %I:%M %p",
    "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M",
)

_SEVERITY_VALUES = {"low": "Low", "medium": "Med", "med": "Med", "high": "High"}
_SEVERITY_NONE = {"", "no damage", "none", "n/a", "na"}

# Form-name → template-name fixes that normalization can't bridge.
# (left side: severity-affix-stripped, _dnorm'd form text; right: _dnorm'd template disease)
_DISEASE_ALIASES = {
    "scleractinia stem rot": "sclerotinia stem rot",   # form typo
    "fusarium stalk rot": "fusaruim stalk rot",        # template typo
    "other disease": "other",
    "other corn disease(s)": "other",
    "other corn diseases": "other",
}


def _hnorm(s: str) -> str:
    """Header normalize: underscores → spaces, collapse whitespace, lowercase.

    Survey123 exports come in two dialects — display aliases ("Date &  Time",
    "TDR Reading #2 - SOIL EC") and raw field names ("Date_Time",
    "TDR_Reading_2_SOIL_EC", truncated at ~31 chars). Folding underscores lets
    one set of rules serve both.
    """
    return " ".join(str(s).replace("_", " ").split()).lower()


# Raw-dialect names that normalization alone can't bridge to the display form.
_HEADER_ALIASES = {
    "date time": "date & time",
    "canola or corn": "canola or corn?",
    "where are you": "where are you?",
    "where are you other": "where are you?",
    "please name the insects": "please name the insect(s)",
    "please take pictures of the dam": "please take pictures of the damage and describe it below",
    "how severe is the damage": "how severe is the damage?",
    "if other explain the growth sta": "if other, explain the growth stage",
    "canola diseases": "canola disease(s)",
    "corn diseases": "corn disease(s)",
    "other corn diseases": "other corn disease(s)",
}
# NOTE: "other disease" stays un-aliased — it's the presence column in the
# display dialect but the free-text column in the raw dialect. The value
# domain decides (Yes/No/severity → Disease_Other; any other text → Notes).


def _dnorm(s: str) -> str:
    """Disease-name normalize: drop punctuation/underscores, collapse, lower."""
    s = str(s).lower().replace("_", " ").replace("/", " ").replace("-", " ")
    s = s.replace("'", "").replace('"', "")
    return " ".join(s.split())


_SEVERITY_SUFFIX_RE = re.compile(r"\s+severit\w*$")  # " severity" + truncations


def _strip_severity_affixes(h: str) -> tuple[str, bool]:
    """Return (disease part, had_severity_affix) for a normalized header."""
    if h.startswith("severity of "):
        return h[len("severity of "):], True
    stripped = _SEVERITY_SUFFIX_RE.sub("", h)
    if stripped != h:
        return stripped, True
    return h, False


def _letters(s: str) -> str:
    """Spacing/punctuation-proof key: letters+digits only, with the known
    cross-dialect typos folded ("Scleractinia" form typo, the raw dialect's
    trailing-digit dedup like "Clubroot2")."""
    key = re.sub(r"[^a-z0-9]", "", s.lower())
    key = re.sub(r"\d+$", "", key)                       # Clubroot2 → clubroot
    key = key.replace("scleractinia", "sclerotinia")     # form typo
    if key.startswith("fusariumstalkrot"):
        key = key.replace("fusariumstalkrot", "fusaruimstalkrot")  # template typo
    return key


# ---- Parsed structures ------------------------------------------------------

@dataclass
class ScoutRow:
    when: datetime
    crop_code: str | None          # canola / corn / None (unknown answer)
    lat: float | None
    lon: float | None
    scouter: str
    pairs: list[tuple[str, str]]   # (normalized header, raw non-empty value)


@dataclass
class ScoutEvent:
    day: date
    rows: list[ScoutRow] = dc_field(default_factory=list)

    @property
    def crop_counts(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for r in self.rows:
            if r.crop_code:
                out[r.crop_code] = out.get(r.crop_code, 0) + 1
        return out

    @property
    def scouters(self) -> list[str]:
        seen: list[str] = []
        for r in self.rows:
            if r.scouter and r.scouter not in seen:
                seen.append(r.scouter)
        return seen


@dataclass
class ParsedScouting:
    path: Path
    events: list[ScoutEvent]       # ordered oldest -> newest
    skipped_no_date: int = 0

    def event(self, day_iso: str) -> ScoutEvent | None:
        for e in self.events:
            if e.day.isoformat() == day_iso:
                return e
        return None


def _parse_when(raw: str) -> datetime | None:
    """Parse a scouting timestamp, tolerant of every dialect ArcGIS/Survey123
    emits: US `M/D/YYYY h:mm:ss AM/PM`, ISO-8601 (with a `T`, optional
    fractional seconds and `Z`/offset), plain `YYYY-MM-DD HH:MM[:SS]`, and the
    feature-service epoch (milliseconds, sometimes seconds). Returns a naive
    local datetime (we only use its date + a `YYYY-MM-DD HH:MM` string)."""
    raw = raw.strip()
    if not raw:
        return None
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue
    # ISO-8601 — handles the `T` separator, fractional seconds, and tz.
    iso = raw.replace("Z", "+00:00") if raw.endswith("Z") else raw
    try:
        return datetime.fromisoformat(iso).replace(tzinfo=None)
    except ValueError:
        pass
    # Epoch timestamp (feature services export numeric millis, sometimes secs).
    if raw.lstrip("-").isdigit():
        try:
            n = int(raw)
            secs = n / 1000 if abs(n) >= 1_000_000_000_000 else n
            return datetime.fromtimestamp(secs)
        except (ValueError, OverflowError, OSError):
            pass
    return None


def _get(pairs: list[tuple[str, str]], header: str) -> str:
    """First non-empty value for a normalized header (coalesces duplicates)."""
    for h, v in pairs:
        if h == header and v:
            return v
    return ""


def parse_scouting_file(path) -> ParsedScouting:
    path = Path(path)
    with open(path, encoding="utf-8-sig", newline="") as fh:
        reader = csv.reader(fh)
        try:
            raw_header = next(reader)
        except StopIteration:
            raise ValueError("Scouting file is empty.")
        headers = [_HEADER_ALIASES.get(_hnorm(h), _hnorm(h)) for h in raw_header]

        by_day: dict[date, ScoutEvent] = {}
        skipped_no_date = 0
        for raw in reader:
            pairs = [(headers[i], raw[i].strip()) for i in range(min(len(headers), len(raw))) if raw[i].strip()]
            if not pairs:
                continue
            when = (_parse_when(_get(pairs, "date & time"))
                    or _parse_when(_get(pairs, "creationdate"))
                    or _parse_when(_get(pairs, "editdate")))
            if when is None:
                skipped_no_date += 1
                continue
            crop = CROP_BY_ANSWER.get(_get(pairs, "canola or corn?").lower() or "")
            lon_s = _get(pairs, "x") or _get(pairs, "longitude")
            lat_s = _get(pairs, "y") or _get(pairs, "latitude")
            try:
                lon = float(lon_s) if lon_s else None
                lat = float(lat_s) if lat_s else None
            except ValueError:
                lon = lat = None
            scouter = _get(pairs, "scouters name") or _get(pairs, "your name")
            ev = by_day.setdefault(when.date(), ScoutEvent(day=when.date()))
            ev.rows.append(ScoutRow(when=when, crop_code=crop, lat=lat, lon=lon, scouter=scouter, pairs=pairs))

    events = [by_day[d] for d in sorted(by_day)]
    return ParsedScouting(path=path, events=events, skipped_no_date=skipped_no_date)


# ---- Translation: one scouting row -> template-column values ---------------

# Both dialects: "#1 TDR - SOIL MOISTURE" / "TDR Readings #1 - SOIL EC" and the
# raw "TDR Reading 2 SOIL TEMPERATURE" / unnumbered "TDR Reading SOIL EC" (= #1).
_TDR_RES = (
    re.compile(r"^#(\d) tdr[ -]+soil (\w+)$"),
    re.compile(r"^tdr readings? #?(\d)[ -]+soil (\w+)$"),
    re.compile(r"^tdr readings?()[ -]+soil (\w+)$"),  # no sensor number → #1
    re.compile(r"^tdr()[ -]+soil (\w+)$"),            # raw "TDR_SOIL_MOISTURE" → #1
)

# Normalized form headers that feed the Notes column, in output order.
# ('"other" disease' = display dialect; 'other disease' = raw dialect text col)
_NOTES_SOURCES = (
    ("optional additional notes", None),
    ("optional notes", None),
    ('"other" disease', "Other disease"),
    ("other disease", "Other disease"),
    ("if other, explain the growth stage", "Growth stage"),
)

_INSECT_ID = "please name the insect(s)"
_INSECT_DESC = "please take pictures of the damage and describe it below"
_INSECT_SEV = "insect damage severity"
_INSECT_SEV_FALLBACK = "how severe is the damage?"

# Question/metadata headers we deliberately never map (not reported as unknown).
_IGNORED_BY_DESIGN = {
    "objectid", "globalid", "creationdate", "creator", "editdate", "editor",
    "x", "y", "latitude", "longitude", "altitude",
    "date & time", "scouters name", "your name", "where are you?",
    "canola or corn?",
    "is there evidence of insect damage?",
    "can you identify which insect did the damage?",
    "are there signs of disease?", "can you identify the disease(s)?",
    "please take pictures of the disease and describe it below. if possible, take a sample back to the lab for identification.",
    "are you collecting any tissue samples for lab analysis?",
    "what kind of tissue samples are you collecting?",
    "how many different diseases are there?",
    "canola disease 2", "disease 2",
    _INSECT_ID, _INSECT_DESC, _INSECT_SEV, _INSECT_SEV_FALLBACK,
    "canola disease(s)", "corn disease(s)",
    "if other, explain the growth stage", '"other" disease',
    "optional additional notes", "optional notes",
    # GPS receiver metadata
    "speed (km/h)", "direction of travel (°)", "compass reading (°)",
    "position source type", "receiver name", "horizontal accuracy (m)",
    "vertical accuracy (m)", "pdop", "hdop", "vdop", "fix type",
    "correction age", "station id", "number of satellites", "fix time",
    "average horizontal accuracy (m)", "average vertical accuracy (m)",
    "averaged positions", "standard deviation (m)", "tilt compensated",
    "tilt angle (°)", "tilt angle accuracy (°)", "tilt azimuth (°)",
    "tilt azimuth accuracy (°)",
    "other disease",  # consumed by the disease/Notes value-domain handling
}


def _bare(s: str) -> str:
    """For ignore-matching: drop the punctuation the two dialects disagree on."""
    return re.sub(r"[?,()\"\.]", "", s).strip()


_IGNORED_BARE = {_bare(h) for h in _IGNORED_BY_DESIGN}


def _is_ignored(header: str) -> bool:
    """Ignored-by-design, tolerant of both export dialects.

    Raw-name exports prefix GPS metadata with `esri…` and truncate long
    question names at ~31 chars, so also accept a bare-prefix match.
    """
    if header in _IGNORED_BY_DESIGN or header.startswith("esri"):
        return True
    bare = _bare(header)
    if bare in _IGNORED_BARE:
        return True
    return len(bare) >= 12 and any(k.startswith(bare) for k in _IGNORED_BARE)


class CropTranslator:
    """Maps one crop's form headers/values onto its template columns."""

    def __init__(self, crop_code: str, template_path) -> None:
        self.crop_code = crop_code
        fields = read_template_fields(template_path)
        self.by_name: dict[str, Field] = {f.name: f for f in fields}
        # Generic header match on the unit-free key (growth stage etc.).
        self.generic: dict[str, str] = {
            _hnorm(f.key.replace("_", " ")): f.name for f in fields
        }
        # Disease maps keyed by punctuation-proof letters keys (see _letters):
        # robust to both export dialects, incl. 31-char truncated raw names.
        self.presence: dict[str, str] = {}
        self.severity: dict[str, str] = {}
        for f in fields:
            if f.kind == FieldKind.DISEASE_PRESENCE:
                self.presence[_letters(_dnorm(f.key.removeprefix("Disease_")))] = f.name
            elif f.kind == FieldKind.SEVERITY and f.key != "Insect_Damage_Severity":
                self.severity[_letters(_dnorm(f.key.removeprefix("Disease_").removesuffix("_Severity")))] = f.name
        # TDR: template key TDR_<n>_SOIL_<kind> -> name
        self.tdr: dict[tuple[str, str], str] = {}
        for f in fields:
            m = re.match(r"^TDR_(\d)_SOIL_(\w+)$", f.key)
            if m:
                self.tdr[(m.group(1), m.group(2).upper())] = f.name

    def _disease_key(self, header: str) -> str | None:
        """Resolve a header to a letters key present in this crop's maps.

        Exact match first; else a unique-prefix match (≥10 chars) to absorb the
        raw dialect's 31-char truncations ("severity of alternaria blackspo").
        """
        stripped, _ = _strip_severity_affixes(header)
        d = _dnorm(stripped)
        key = _letters(_DISEASE_ALIASES.get(d, d))
        if not key:
            return None
        if key in self.presence or key in self.severity:
            return key
        if len(key) >= 10:
            hits = {k for k in (*self.presence, *self.severity) if k.startswith(key)}
            if len(hits) == 1:
                return next(iter(hits))
        return None

    def _disease_target(self, header: str, value: str) -> tuple[str, str] | None:
        """Resolve a disease-ish header+value to (template column, value)."""
        d = self._disease_key(header)
        if d is None:
            return None
        vlow = value.strip().lower()
        if vlow == "yes" and d in self.presence:
            return (self.presence[d], "yes")
        if vlow in _SEVERITY_VALUES and d in self.severity:
            return (self.severity[d], _SEVERITY_VALUES[vlow])
        if vlow in ("no",) or vlow in _SEVERITY_NONE:
            # Known column, nothing to write.
            return (self.presence.get(d) or self.severity[d], "")
        # Free text under a disease-named header (the raw dialect's
        # "Other_disease" text column) — not ours; let it reach the Notes path.
        return None

    def translate(self, row: ScoutRow) -> tuple[dict[str, str], list[str]]:
        """Return ({template column: value}, [unmapped headers with data])."""
        values: dict[str, str] = {}
        unmapped: list[str] = []
        notes: list[str] = []

        for header, value in row.pairs:
            # TDR sensors
            tdr_hit = None
            for rx in _TDR_RES:
                m = rx.match(header)
                if m:
                    tdr_hit = self.tdr.get((m.group(1) or "1", m.group(2).upper()))
                    break
            if tdr_hit:
                values[tdr_hit] = value
                continue
            # Date & Time -> Date_Time (normalized, sortable)
            if header == "date & time":
                if row.when:
                    values["Date_Time"] = row.when.strftime("%Y-%m-%d %H:%M")
                continue
            # Diseases (presence or severity, decided by value domain)
            hit = self._disease_target(header, value)
            if hit:
                col, v = hit
                if v:
                    values[col] = v
                continue
            # Another crop's disease column riding along in this row — skip,
            # but only for presence/severity-domain values (free text under a
            # disease-ish name still falls through to the Notes path below).
            vlow = value.strip().lower()
            if (vlow in ("yes", "no") or vlow in _SEVERITY_VALUES or vlow in _SEVERITY_NONE) \
                    and _is_any_crop_disease(header):
                continue
            # Generic key match (growth stages etc.)
            g = self.generic.get(header)
            if g:
                values[g] = value
                continue
            if _is_ignored(header):
                continue
            unmapped.append(header)

        # Insects (explicit, outside the loop so fallbacks order cleanly)
        ident = _get(row.pairs, _INSECT_ID)
        if ident and ident.strip().lower() not in ("none", "n/a", "na"):
            values["Insect_Identification"] = ident
        desc = _get(row.pairs, _INSECT_DESC)
        if desc:
            values["Insect_Damage"] = desc
        sev = _get(row.pairs, _INSECT_SEV) or _get(row.pairs, _INSECT_SEV_FALLBACK)
        if sev:
            vlow = sev.strip().lower()
            if vlow in _SEVERITY_VALUES:
                values["Insect_Damage_Severity"] = _SEVERITY_VALUES[vlow]

        # Old-form fallback: "<Crop> Disease(s)" multiselect -> presence yes.
        for ms_header in ("canola disease(s)", "corn disease(s)"):
            ms = _get(row.pairs, ms_header)
            if not ms:
                continue
            for name in re.split(r"[;,]", ms):
                d = _dnorm(name)
                key = _letters(_DISEASE_ALIASES.get(d, d))
                if key in self.presence:
                    values[self.presence[key]] = "yes"

        # Notes ("other disease" carries free text only in the raw dialect —
        # Yes/No/severity values belong to the presence column and are skipped)
        for src, label in _NOTES_SOURCES:
            v = _get(row.pairs, src)
            if not v:
                continue
            vlow = v.strip().lower()
            if label == "Other disease" and (vlow in ("yes", "no") or vlow in _SEVERITY_VALUES or vlow in _SEVERITY_NONE):
                continue
            notes.append(f"{label}: {v}" if label else v)
        if notes and "Notes" in self.by_name:
            values["Notes"] = "; ".join(notes)

        return values, unmapped
