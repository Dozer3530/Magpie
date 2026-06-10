# Frontend parity checklist

Magpie has two frontends — the **PySide6 desktop** (`app/ui/`) and the **local
web app** (`webapp/`) — and they must never drift. Both are thin shells over
the same `app/services/` layer, so "no drift" is structural, not a matter of
discipline: there is only one implementation of every action.

This is the map. Every user-facing action lists the **service function** that
does the real work, the **desktop** entry point that calls it, and the **web**
route that calls the *same* function. When you change behavior, you change the
service — both columns inherit it for free.

| Action | Service (the brain) | Desktop (`app/ui/`) | Web (`webapp/server.py`) |
|---|---|---|---|
| List crops | `crops.CROPS` | crop selector | `GET /api/crops` |
| Current ISO week | `weeks.current_iso_week` | `main_window` | `GET /api/weeks` (`current`) |
| List weeks | `weeks.list_week_rows` | week selector | `GET /api/weeks` (`weeks`) |
| Auto-seed current week on launch | `weeks.ensure_current_week` | `main_window` startup | `lifespan` startup |
| Create week | `weeks.create_week` | week toolbar | `POST /api/weeks` |
| Delete week | `weeks.delete_week` | week toolbar | `DELETE /api/weeks/{tag}` |
| Rename a week's code (PK migration) | `weeks.rename_week` (→ `db.rename_week`, `image_storage.rename_week_dirs`) | Weeks tab + week toolbar | `POST /api/weeks/rename` |
| Multi-week Field/Lab progress | `weeks.all_weeks_progress` (uses `schema.field_page_names`/`lab_page_names`) | Weeks tab (`app/ui/weeks_tab.py`) | `GET /api/weeks/progress` |
| Week overview / per-location status | `exports.week_status` | Week-overview tab | `GET /api/overview` |
| Observation form layout | `observations.build_form_schema` | Observations tab (`_rebuild_form`) | `GET /api/form-schema` |
| Load one location's row | `observations.load` | Observations tab | `GET /api/obs` |
| Save one location's row | `observations.save` | Observations tab | `PUT /api/obs` |
| Read lab file + auto-map columns | `imports.prepare` | Lab Import tab (browse) | `POST /api/import/upload` |
| Read scouting export (events + GPS assignment preview) | `scouting.prepare` (`importers/scouting.py`) | Survey123 Import tab (browse) | `POST /api/scouting/upload` |
| Commit a scouting event (both crops, GPS join) | `scouting.commit` | Survey123 Import tab | `POST /api/scouting/commit` |
| Commit lab import (+ dup-target guard) | `imports.commit_lab` (`DuplicateTargetError`) | Lab Import tab | `POST /api/import/lab` (409 on dup) |
| Read Pest ID sheet (crop auto-detect + week list) | `pests.prepare` (`importers/pest.py`) | Pest ID tab (browse) | `POST /api/pest/upload` |
| Commit a pest week → current week | `pests.commit` | Pest ID tab | `POST /api/pest/commit` |
| Pest "uploaded" status | `pests.pest_status` | Pest ID tab status line | `GET /api/pest/status` |
| Pest bug block in export | `pests.export_block` (→ `excel_export._write_pest_block`) | (export) | (export) |
| Build one crop's package | `exports.build_week_package` | Export tab | `POST /api/export` |
| Build all crops' package | `exports.build_all` | Export tab | `POST /api/export-all` |
| Download the zip | (file on disk) | opens folder | `GET /api/export/{week}/download` |
| List a location's photos | `image_storage.list_existing` | image widget | `GET /api/images` |
| Serve a photo | `image_storage.absolute_path` | image widget | `GET /api/images/file` |
| Attach a photo | `image_storage.attach` | image widget | `POST /api/images` |
| Back up the database | `maintenance.create_backup` (→ `db.backup_database`) | "Back up data" button + `backup.bat` | `POST /api/backup` |
| Publish shareable progress page | `publish.publish_progress` (+ get/set_publish_dir; auto after export) | "Publish progress" button (folder picker) | `POST /api/publish` · `GET/PUT /api/publish/dir` |
| Week-over-week trends (soil / disease+growth / nutrients / ratios) | `trends.trend_series` (category, field avg or per-point) | Trends tab (`app/ui/trends_tab.py`, category combo + delta table) | `GET /api/trends?cat=` (category select + SVG charts) |

## Known, accepted differences (UX only — never output)

- **File picking.** Desktop uses a native dialog and remembers the last-used
  folder (`app/app_settings.py`, desktop-only). Web uploads the file to the
  local server. Functionally equivalent; the *imported data* is identical.
- **Two-step import state.** The web flow persists the uploaded temp file and
  re-reads it on commit (token-keyed), where the desktop holds the parsed
  `LoadedFile` in memory between browse and commit. Same `prepare` →
  `commit_*` calls, same result.
- **Progress display.** Desktop shows Qt progress; web animates stages in JS.
  Cosmetic only — both call the one export service and write the same files.
- **Trend visualization.** Web draws SVG line charts; desktop shows a
  values + delta-arrow table. Same `trends.soil_trends` data behind both.

## The automated guarantee

`tests/test_parity.py::test_desktop_and_web_exports_match` seeds one set of
observations, builds the week through the service layer directly (the desktop
path) **and** through the web `/api/export` route, then asserts the produced
Excel (cell-for-cell) and GeoPackage (geometry + attribute table) are
content-identical. If a change ever makes the two frontends diverge on output,
this test fails.

When you add a feature: add the logic to `app/services/`, wire both frontends
to it, and — if it produces an export artifact — extend the parity test.

Both frontends are now feature-complete against the service layer — every row
above has a desktop entry point and a web route calling the same function.
