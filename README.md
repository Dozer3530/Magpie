<p align="center">
  <img src="assets/logo.png" alt="Magpie logo" width="220">
</p>

# Magpie

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

**Magpie builds the weekly crop-monitoring data package.** It funnels three
field/lab feeds into a per-crop store and exports a single, client-ready
deliverable — a stamped Excel workbook, a matching GeoPackage, the photos, and
one `.zip` — for each crop, every week.

Run it as a **desktop app** or a **local web app in your browser** — they share
one engine, so they always produce the same output.

---

## What it does

Each week you collect data at 9 fixed monitoring points per crop (Canola
`M1`–`M9`, Corn `L1`–`L9`; more crops drop in). Three upstream feeds flow into
each weekly package:

- **Survey123** field observations — disease presence & severity, TDR soil
  sensors, insect notes, growth stage, photos.
- **PT2R lab reports** — the full nutrient panel plus sufficiency ratings and
  expected-ratio columns.
- **Pest ID** — a living per-field bug-count log; you pick which week to pull.

Magpie merges them into the per-crop template the client already expects, plus
a matching GeoPackage for GIS, plus a single `.zip` you can hand off. It also
keeps the week-over-week history so you can watch trends and coverage build up.

---

## Setup

For a colleague setting this up fresh on a Windows PC.

### 1. Prerequisites

- **Python 3.11+** — install from [python.org](https://www.python.org/downloads/),
  and **tick "Add Python to PATH"** in the installer. Verify in a new terminal:
  ```
  python --version
  ```
- **Git** — install from [git-scm.com](https://git-scm.com/download/win) (or use
  GitHub Desktop). Needed to clone the repo and pull updates.
- **Access to the repo** — it's private; ask the owner (Dozer3530) to add you.

### 2. Get the code

```
git clone https://github.com/Dozer3530/Magpie.git
cd Magpie
```
(The repo folder may be named "Earth Daily Package Organizer and Creator" — the
product is Magpie.)

### 3. Install the dependencies

```
pip install -r requirements-web.txt
```
That installs everything: the core libraries plus the web frontend (FastAPI,
uvicorn). If you only ever want the desktop app, `pip install -r requirements.txt`
is enough.

### 4. First run

```
python -m webapp
```
Your browser opens to **http://127.0.0.1:8000**. First launch creates the
current week and seeds the monitoring points automatically. Keep the terminal
window open while you work; close it (or Ctrl+C) to stop.

> **Updating later:** `git pull`, then re-run. After any update, **hard-refresh
> the browser (Ctrl+Shift+R)** so it picks up the new page.

### 5. (Optional) one-click desktop launcher

Make a Windows shortcut to **`run-web.bat`** and set its icon to
`assets/magpie.ico`. Double-clicking it starts the server and opens your
browser; close the window to stop. (There's also `run.bat` for the desktop app.)

---

## Run

Two frontends, **one shared core** — pick whichever you prefer; they produce
byte-equivalent packages because both call the same `app/services/` layer.

**Local web app** (browser → `127.0.0.1:8000`): double-click `run-web.bat`, or
`python -m webapp`.

**Desktop app** (PySide6 window): double-click `run.bat`, or `python -m app`.

> **Run one frontend at a time** against the same `packages.sqlite`. It's a
> single-user tool, so this is fine — two simultaneous editors of one row is a
> conflict SQLite won't resolve. (The DB runs in WAL mode, which makes
> incidental concurrent *reads* painless, but it isn't multi-writer safe by
> intent.)

> **Local & private by design.** The web server binds `127.0.0.1` only — never
> `0.0.0.0`, no auth, never exposed to the network. The templates carry real
> client monitoring-point coordinates, so the repo stays **private**.

---

## The weekly workflow

Both frontends present the same eight views:

1. **Weeks** — the multi-week dashboard. Every week with three completeness
   tracks per crop: **Field** (Survey123), **Lab** (PT2R), and **Pest** (cards
   completed). Open, **rename** (the code is also the export filename), delete,
   or create a week. Field lands first; Lab and Pest fill in as results arrive.
2. **Week overview** — for the active crop + week, how many template fields each
   monitoring point carries, plus the Pest ID upload status.
3. **Survey123 Import** — upload the survey export; columns auto-map to the
   template by name; photos in a sibling `media/` folder get copied in.
4. **Lab Import** — upload the PT2R `.xls`; assign each lab row to a monitoring
   point (the lab's `SampleID` doesn't map automatically).
5. **Pest ID Import** — upload the field's living pest sheet. Magpie detects the
   crop from the point IDs (`M`=Canola, `L`=Corn); you pick which **sheet week**
   to pull and it attaches to the current week. Only the bug types seen that
   week land in the package.
6. **Observations** — everything merged from the feeds, hand-editable before
   export, split into Field / Lab sub-tabs. Attach extra photos here.
7. **Export** — produces the deliverable in `exports/<week>/`:
   - `<Crop>_<week>.xlsx` — the template, filled in (styling preserved, columns
     auto-sized; a colored pest block sits before the lab nutrients when bugs
     were recorded that week)
   - `<Crop>_<week>.gpkg` — the same data as a Point layer (EPSG:4326)
   - `images/<crop>/<loc>/…` — the photo files
   - `EarthDaily_<week>.zip` — the one-file deliverable
8. **Trends** — week-over-week, field-average or per-point, with a category
   picker: soil readings, disease & growth, nutrients, ratios, and pest counts.

The `Images` column in the exported `.xlsx` becomes a `HYPERLINK` formula — the
client unzips, clicks the cell, and the photo (or the location's photo folder)
opens.

---

## Two frontends, one core

The whole point of the architecture: a feature, bug fix, or template change
takes effect in **both** frontends without editing two copies. All real logic —
DB, schema, importers, exporters, merge policy, zip, photo handling, the
observation form structure, trends, backups — lives in a UI-agnostic service
layer (`app/services/`). The PySide6 desktop (`app/ui/`) and the FastAPI web
server (`webapp/`) are thin shells that call the same functions.

```
        app/services/   ← the brain (pure Python; no Qt, no HTTP)
  weeks · observations · imports · exports · trends · pests · maintenance
              │                                   │
        app/ui/  (PySide6 tabs)             webapp/  (FastAPI routes + static JS)
```

`docs/PARITY.md` maps every user action → service → desktop entry point → web
route, and has no pending rows. `tests/test_parity.py` builds a week through the
service layer *and* through the web `/api/export` route and asserts the Excel +
GeoPackage come out content-identical — the automated guarantee that the two
never drift.

---

## Backups

`packages.sqlite` is the single source of truth (and git-ignored), so back it up
once it holds real weeks. Three equivalent ways, all WAL-consistent snapshots
into `data/backups/`:

- double-click **`backup.bat`**,
- hit **Back up data** in either frontend, or
- run `python -m app.services.maintenance`.

Each writes `packages_<timestamp>.sqlite` — a normal SQLite file you can open
directly or swap back in for `data/packages.sqlite` to restore.

---

## Share progress with coworkers (live page)

Magpie can publish a **self-refreshing progress page** so colleagues can *watch*
how far along each week is — without editing access or a server.

- Pick a **synced folder** once — point it at your **Google Drive for Desktop**
  folder (or OneDrive / a network share). On desktop, **Publish progress** opens
  a folder picker; on the web Weeks view, paste the folder path next to the
  **Publish progress** button.
- It writes one self-contained file, **`magpie-progress.html`** — the Weeks
  dashboard (each week's Field/Lab/Pest counts per crop) with an "Updated &lt;time&gt;"
  stamp. It **re-publishes automatically after every export**, plus the manual
  button any time.
- Coworkers **open the synced local copy** (e.g. `G:\My Drive\…\magpie-progress.html`)
  in a browser; it **refreshes itself** and Drive syncs new versions, so it
  stays current. It shows only completeness counts — no coordinates — so it's
  safe to share.

> Open the **synced file**, not the Google Drive *website* — Drive no longer
> renders HTML, so the website just downloads it. "Live" here means the open
> page self-refreshes and reflects the last publish; truly real-time would need
> a hosted server.

---

## How the templates work

`Static Canola Template.xlsx` and `Static Corn Template.xlsx` (repo root) are the
**source of truth** for column layout. Magpie reads their row-1 headers at
startup and uses them to generate the `obs_<crop>` tables, lay out the dynamic
form, drive the importers, and stamp the export (exports are just template
copies with row data filled in, so the client's styling is preserved).

Adding a crop is a three-step drop-in — no Python changes outside the registry:

1. Drop `Static <Crop> Template.xlsx` next to the others, same shape
   (col A = ID, col B = Location, row 1 = headers).
2. Write `app/growth_stages/<crop>.py` exposing `STAGES: list[tuple[str, str]]`
   of (BBCH code, description).
3. Append a `CropConfig` entry to `app/crops.py`.

---

## Data conventions

- Disease presence columns hold `"yes"` or blank. Severity is `Low` / `Med` /
  `High` or blank (bands: Low 1–10%, Med 10–30%, High >30%). Insect damage uses
  the same scale.
- Nutrient `_rate` columns are PT2R letter codes (`D` / `L` / `S` / `H` / `VH`).
- Units are baked into the headers (`N (%)`, `Zn (ppm)`, `TDR_1_SOIL_TEMPERATURE
  (°C)`); internal logic matches on a unit-stripped key, so the unit text never
  breaks classification or import.
- Everything is stored as TEXT so values round-trip the templates
  byte-equivalent.
- Locations are fixed across weeks; their lat/long lives in the templates.

---

## Testing

```
python -m pytest -q
```
67 tests covering schema, DB, importers (incl. pest), services, the golden
export, the pest export block, trends, and the desktop↔web export parity. The
`tests/conftest.py` `isolated_db` fixture redirects the DB + image storage into
a temp folder, so tests never touch your real `data/`.

---

## Repository layout

```
app/
├── __main__.py            desktop entry point (python -m app)
├── config.py              paths
├── crops.py               crop registry (adding a crop = edit this)
├── schema.py              template headers → typed fields + Field/Lab split
├── db.py                  SQLite schema, helpers, rename/backup
├── app_settings.py        last-used folders (desktop-only)
├── image_storage.py       photo storage layer
├── growth_stages/         per-crop BBCH lists
├── importers/             survey123 / lab loaders + pest.py parser
├── exporters/             xlsx (+ pest block) / gpkg / photo-copy / zip
├── services/              UI-agnostic brain both frontends call
│   ├── weeks.py             ISO week + CRUD + rename + all_weeks_progress
│   ├── observations.py      load/save + build_form_schema (shared form layout)
│   ├── imports.py           commit_survey / commit_lab orchestration
│   ├── exports.py           build_week_package / build_all + week_status
│   ├── trends.py            week-over-week series by category
│   ├── pests.py             Pest ID parse / commit / status / export block
│   ├── maintenance.py       one-click WAL-safe DB backup
│   └── publish.py           shareable self-refreshing progress page
└── ui/                    PySide6 tabs (thin: widgets only)

webapp/
├── __main__.py            web entry point (python -m webapp → 127.0.0.1:8000)
├── server.py              FastAPI routes — 1:1 thin shell over app/services
├── serialize.py           the one place service dataclasses → JSON
└── static/index.html      browser frontend (vanilla JS, no build step)

docs/PARITY.md                every action ↔ desktop ↔ web (no pending rows)
Static Canola Template.xlsx   column-layout source of truth
Static Corn Template.xlsx     "
requirements.txt              desktop deps
requirements-web.txt          + FastAPI / uvicorn / multipart
run.bat · run-web.bat · backup.bat   one-click launchers
data/                         generated DB + photos + backups (gitignored)
exports/                      generated weekly packages (gitignored)
tests/                        pytest safety net (incl. desktop↔web parity)
```

---

## License

MIT — see [LICENSE](LICENSE).
