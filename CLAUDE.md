# CLAUDE.md — Magpie

Guide for AI sessions in this repo. The folder is named "Earth Daily Package
Organizer and Creator"; the product is **Magpie**.

## What it is
A weekly crop-monitoring package builder. It funnels Survey123 field data +
PT2R lab results into a per-crop SQLite store and exports a weekly deliverable
(stamped Excel + GeoPackage + photos + zip). Single-user, local, Windows.

## The one rule: one core, two thin frontends — never duplicate logic
All real logic lives in `app/services/` (UI-agnostic pure Python). Two thin
frontends call it and must stay in lockstep:
- **Desktop** — PySide6, `app/ui/`, launch `python -m app` (or `run.bat`).
- **Web** — FastAPI on `127.0.0.1:8000`, `webapp/`, launch `python -m webapp`
  (or `run-web.bat`). Frontend is `webapp/static/index.html` (vanilla JS).

When adding a feature: put logic in `app/services/`, then wire BOTH frontends
to it. `docs/PARITY.md` maps every action → service → desktop → web and must
have no pending rows. Keep it that way.

Services: `weeks` (CRUD + `rename_week` + `all_weeks_progress`), `observations`
(`build_form_schema` + load/save), `imports` (lab), `scouting` (the real
Survey123 feed: `prepare`/`commit` — GPS join, event slices, both crops),
`reactive` (`prepare`/`commit`/`week_points` — the client-scattered "reactive"
points in non-home fields; CSV-supplied locations, per-field numbering),
`exports` (+ `week_status`), `trends` (`trend_series`), `maintenance`
(`create_backup`), `pests` (`prepare`/`commit`/`pest_status`/`export_block` —
the Pest ID feed), `publish` (`publish_progress` — shareable self-refreshing
progress page to a synced folder; auto-runs after each export).

## Templates are the source of truth
`Static Canola Template.xlsx` / `Static Corn Template.xlsx` (repo root): row 1
headers drive the DB schema, forms, importers, and export. `app/schema.py`
classifies headers into typed `Field`s; `page_of` splits field- vs lab-page
columns (used by the Weeks dashboard, Observations form, trends, fake-CSV gen).
Add a crop = drop a template + `app/growth_stages/<crop>.py` + a `CropConfig`
in `app/crops.py`. No other code changes.

## Commands
- Tests: `python -m pytest -q` (99 tests; `tests/conftest.py` `isolated_db`
  fixture monkeypatches `db.DB_PATH` / `image_storage.IMAGES_ROOT` into tmp).
- Run web: `python -m webapp` · Run desktop: `python -m app`
- Back up the DB: `backup.bat` or `python -m app.services.maintenance`
- Generate fake import CSVs (local only): `python sample_imports/_generate.py`

## Conventions / constraints (do not violate)
- **Web binds `127.0.0.1` only — never `0.0.0.0`, no auth.** Templates carry
  real client monitoring-point coordinates. Repo stays **PRIVATE**.
- **Run one frontend at a time** against the same `data/packages.sqlite`
  (single-user; WAL is on but it's not multi-writer safe).
- All obs values stored as **TEXT** so they round-trip the templates
  byte-equivalent (disease = "yes"/blank, severity = Low/Med/High, etc.).
- Git: commit/push only when asked; end commit messages with
  `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.
- `gh` CLI is not on PATH — use `"C:\Program Files\GitHub CLI\gh.exe"`.
  Git identity: Dozer3530 / zachkom@telus.net. Repo: github.com/Dozer3530/Magpie
  (private). Current release: **v1.4.0** (Latest).

## Local-only (git-ignored, keep out of commits)
`data/` (DB, photos, backups), `exports/`, `sample_imports/` (fake CSVs carry
real coords), `demo/themes/` (theme gallery).

## Gotchas
- Windows console is **cp1252** — avoid non-ASCII in `print()`/banners (it
  crashes). `webapp/static/index.html` can use Unicode freely.
- PowerShell single-quoted here-strings break if the message contains `"` —
  keep commit messages free of double quotes.
- Excel export auto-fits column widths (`_autofit_columns`).
- Pest ID is a third feed: a living per-field CSV (`<point>_<weekIndex>` IDs,
  crop from M/L prefix, variable bug columns) stored in `pest_obs` (bugs as
  JSON). On import you pick the sheet-week → it attaches to the current ISO
  week. Export inserts a green bug block **before the lab columns, only when
  that week has bugs** (so normal exports are unchanged).
- The REAL Survey123 export (`importers/scouting.py`) has NO point IDs — rows
  are GPS-joined to the nearest stake (50 m tolerance; stakes ≥106 m apart so
  matches are provably unique). One cumulative file, both crops, events by
  date; the user picks the event. It comes in TWO header dialects (display
  aliases vs raw underscore names truncated at ~31 chars) — both handled; the
  form has a "Scleractinia" typo and the corn template a "Fusaruim" typo
  (explicit aliases). Free-text notes land in the templates' `Notes` column
  (added 2026-06; last column of both templates).
- "Reactive" feed (`services/reactive.py`): the SAME cumulative CSV also carries
  client-scattered one-off points in non-home fields. `importers/scouting.py`
  has `HOME_FIELDS = {field 17, field 18}` + `ScoutRow.field`; rows are
  partitioned by field name — home → scouting (GPS-joined to stakes, non-home
  rows get status `other_field`), everything else → reactive. Reactive points
  keep their OWN CSV lat/lon (no stake match), are Survey123-only (no lab), and
  store in `reactive_obs` (values as JSON). The display ID (`F1, F2…`) is
  DERIVED from chronological order per field (spans weeks + both crops), so a
  later batch continues the count and re-imports are idempotent. Templates are
  the lighter `Reactive <Crop> Template.xlsx` (Static minus lab columns + a
  `Field` column; rebuild via `tools/build_reactive_templates.py`). Export
  writes `Reactive_<Crop>_<week>.xlsx`/`.gpkg` into the SAME week folder (so the
  zip bundles them) ONLY when the week has reactive points — so normal exports
  are byte-unchanged. Reactive is intentionally excluded from Trends + the Weeks
  dashboard (ephemeral, no week-over-week identity).

## Open actions
- When the first real PT2R lab file arrives, confirm units for **NO3N / Na /
  Cl** (% vs ppm) in `UNIT_BY_KEY` (`app/schema.py`). Currently NO3N=ppm,
  Na=%, Cl=%.
