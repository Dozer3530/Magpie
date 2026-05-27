<img src="assets/logo.png" align="left" width="110" alt="Magpie logo" />

# Magpie

Weekly crop-monitoring package builder. Funnels Survey123 field observations,
PT2R lab reports, and photos into a single per-crop Excel + GeoPackage
deliverable for the client.

Point it at a Survey123 export and a lab `.xls`, assign each lab row to a
monitoring point, click Export — you get a zipped weekly package with the
template filled in and photos hyperlinked from the right rows.

## What it does

Each week you collect data at 9 fixed monitoring points per crop (Canola
`M1`–`M9`, Corn `L1`–`L9`, plus future crops). Two upstream sources feed
each weekly package:

- **Survey123** field observations — disease presence, severity, TDR soil
  sensors, insect notes, growth stage, photos.
- **PT2R lab reports** — full nutrient panel plus sufficiency ratings and
  expected-ratio columns.

Magpie merges both into per-crop templates that match the column layout your
client already expects, plus a matching GeoPackage for GIS work, plus a
single `.zip` you can email.

## Install

```
pip install -r requirements.txt
```

Tested on Python 3.11+ on Windows. Uses PySide6, openpyxl, python-calamine
(reads legacy `.xls`), pandas, geopandas / pyogrio / shapely.

## Run

Double-click `run.bat`, or:

```
python -m app
```

First launch auto-creates the current ISO week and seeds the database with
the locations + growth stages defined in `app/crops.py`.

## Weekly workflow

Five tabs, in order:

1. **Week overview** — pick the crop + week. See which monitoring points
   already have data and which are still empty.
2. **Survey123 Import** — browse to the survey export. Photos in a sibling
   `media/` folder get auto-copied into the app's image storage.
3. **Lab Import** — browse to the PT2R `.xls`. Each lab row gets a
   `Target location` dropdown (M1–M9 / L1–L9 / Skip) — assign by hand
   since the lab's `SampleID` doesn't map automatically.
4. **Observations** — split into *Field observations* and *Lab report*
   sub-tabs. Hand-edit anything before export; attach extra photos here
   if Survey123 didn't catch them.
5. **Export** — produces the deliverable:
   - `exports/<YYYY-Www>/Canola_<YYYY-Www>.xlsx` — the template, filled in
   - `exports/<YYYY-Www>/Canola_<YYYY-Www>.gpkg` — same data, Point layer
   - `exports/<YYYY-Www>/images/canola/M1/…` — photo files
   - `exports/<YYYY-Www>/EarthDaily_<YYYY-Www>.zip` — one-file deliverable

The `Images` column in the exported `.xlsx` becomes a `HYPERLINK` formula —
client unzips the package, clicks the cell, and the photo (or the
location's photo folder, if there are several) opens.

## How the templates work

The shipped `Static Canola Template.xlsx` and `Static Corn Template.xlsx`
files in the repo root are the **source of truth** for column layout. Magpie
reads their headers at startup and uses them to:

- generate the `obs_<crop>` SQLite tables
- lay out the dynamic form fields
- drive the Excel export (preserves template styling — exports are just
  template copies with row data stamped in)

Adding a third crop is a three-step drop-in — no Python changes outside the
registry:

1. Drop `Static <Crop> Template.xlsx` next to the existing templates,
   matching the same shape (col A = ID, col B = Location, row 1 = headers).
2. Write `app/growth_stages/<crop>.py` exposing `STAGES: list[tuple[str, str]]`
   of (BBCH code, description).
3. Append a `CropConfig` entry to `app/crops.py`.

This pathway is tested — see the wheat drop-in integration test in
`test_*` (run ad-hoc; see commit history).

## Data conventions

- Disease presence columns hold `"yes"` or blank. Severity is `Low` / `Med` /
  `High` or blank.
- Nutrient `_rate` columns are PT2R letter codes (`D` / `L` / `S` / `H` /
  `VH`) — editable combo boxes accept any one-off lab code without losing
  it.
- Locations are fixed across weeks; their lat/long lives in the templates.
- One client, one output set per week. No multi-tenant model.

## Repository layout

```
app/
├── __main__.py            entry point (python -m app)
├── config.py              paths
├── crops.py               crop registry (adding a 3rd crop = edit this)
├── schema.py              reads template headers → typed field metadata
├── db.py                  SQLite schema + helpers
├── app_settings.py        last-used folder etc.
├── image_storage.py       photo storage layer
├── growth_stages/         per-crop BBCH lists
├── importers/             Survey123 + lab CSV/xls loaders
├── exporters/             xlsx + gpkg + photo-copy + zip
└── ui/                    PySide6 tabs

Static Canola Template.xlsx   column-layout source of truth
Static Corn Template.xlsx     "
data/                         generated DB + photos (gitignored)
exports/                      generated weekly packages (gitignored)
```

## License

MIT.
