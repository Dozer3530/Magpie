<p align="center">
  <img src="assets/logo.png" alt="Magpie logo" width="220">
</p>

# Magpie

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Weekly crop-monitoring package builder. Funnels Survey123 field observations,
PT2R lab reports, and photos into a single per-crop Excel + GeoPackage
deliverable for the client.

A companion to [Perch](https://github.com/Dozer3530/Perch) and
[Lapwing](https://github.com/Dozer3530/Lapwing) — Perch lands drone imagery,
Lapwing watches from above, Magpie assembles the weekly package.

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
pip install -r requirements.txt          # desktop app
pip install -r requirements-web.txt       # + the local web frontend
```

`requirements-web.txt` pulls in everything in `requirements.txt` plus FastAPI,
uvicorn, and python-multipart — install it only if you want the browser
frontend. The desktop app runs without the web dependencies.

Tested on Python 3.11+ on Windows. Uses PySide6, openpyxl, python-calamine
(reads legacy `.xls`), pandas, geopandas / pyogrio / shapely.

## Run

Two frontends, **one shared core** — pick whichever you prefer; they produce
byte-equivalent packages because both call the same `app/services/` layer.

**Desktop (PySide6):** double-click `run.bat`, or:

```
python -m app
```

**Local web app (browser → `127.0.0.1:8000`):** double-click `run-web.bat`, or:

```
python -m webapp
```

It opens your browser to a local FastAPI server bound to `127.0.0.1` only —
single-user, no auth, never exposed to the network (the templates carry real
client monitoring-point coordinates).

> **Run one frontend at a time** against the same `packages.sqlite`. It's a
> single-user tool, so this is fine — but two simultaneous editors of one row
> is a logical conflict SQLite won't resolve. (The DB runs in WAL mode, which
> makes incidental concurrent *reads* painless, but it is not multi-writer
> safe by intent.)

Either way, first launch auto-creates the current ISO week and seeds the
database with the locations + growth stages defined in `app/crops.py`.

## Two frontends, one core

The whole point of the architecture is that a feature, bug fix, or template
change takes effect in **both** frontends without editing two copies. All real
logic — DB, schema, importers, exporters, merge policy, zip, photo handling,
the observation form structure — lives in a UI-agnostic service layer
(`app/services/`). The PySide6 desktop (`app/ui/`) and the FastAPI web server
(`webapp/`) are both thin presentation shells that call the same service
functions.

```
        app/services/   ← the brain (pure Python; no Qt, no HTTP)
        weeks · observations(+form schema) · imports · exports · status
              │                                   │
        app/ui/  (PySide6 widgets)          webapp/  (FastAPI routes + static JS)
```

A `tests/test_parity.py` test seeds one set of observations, builds the week
through the service layer *and* through the web `/api/export` route, and
asserts the Excel + GeoPackage come out content-identical — the automated
guarantee that the two frontends never drift.

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
  `High` or blank (bands: Low 1–10%, Med 10–30%, High >30% of the plant).
  Insect damage uses the same severity scale (`Insect_Damage_Severity`).
- Nutrient `_rate` columns are PT2R letter codes (`D` / `L` / `S` / `H` /
  `VH`) — editable combo boxes accept any one-off lab code without losing
  it.
- Measurement units are baked into the template headers (e.g. `N (%)`,
  `Zn (ppm)`, `TDR_1_SOIL_TEMPERATURE (°C)`). Internal logic matches on a
  unit-stripped key, so the unit text never breaks classification or import.
- Locations are fixed across weeks; their lat/long lives in the templates.
- One client, one output set per week. No multi-tenant model.

## Repository layout

```
app/
├── __main__.py            desktop entry point (python -m app)
├── config.py              paths
├── crops.py               crop registry (adding a 3rd crop = edit this)
├── schema.py              reads template headers → typed field metadata
├── db.py                  SQLite schema + helpers
├── app_settings.py        last-used folder etc. (desktop-only)
├── image_storage.py       photo storage layer
├── growth_stages/         per-crop BBCH lists
├── importers/             Survey123 + lab CSV/xls loaders
├── exporters/             xlsx + gpkg + photo-copy + zip
├── services/              UI-agnostic brain both frontends call
│   ├── weeks.py             ISO-week calc + create/delete/list
│   ├── observations.py      load/save + build_form_schema (shared form layout)
│   ├── imports.py           commit_survey / commit_lab orchestration
│   └── exports.py           build_week_package / build_all + week_status
└── ui/                    PySide6 tabs (thin: widgets only)

webapp/
├── __main__.py            web entry point (python -m webapp → 127.0.0.1:8000)
├── server.py              FastAPI routes — 1:1 thin shell over app/services
├── serialize.py           the one place service dataclasses → JSON
└── static/index.html      browser frontend (vanilla JS, no build step)

Static Canola Template.xlsx   column-layout source of truth
Static Corn Template.xlsx     "
requirements.txt              desktop deps
requirements-web.txt          + FastAPI / uvicorn / multipart
data/                         generated DB + photos (gitignored)
exports/                      generated weekly packages (gitignored)
tests/                        pytest safety net (incl. desktop↔web parity)
```

## License

MIT.
