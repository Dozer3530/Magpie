"""Survey123 import tab.

Loads a Survey123 CSV/XLSX, auto-maps source columns to the active crop's
template fields by exact name match, and writes each row into `obs_<crop>`
for the currently-selected week. The join column from source to location is
the column the user marks as the location ID (defaults to whichever source
column auto-mapped to the template's `ID`).
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app import app_settings, image_storage
from app.crops import crop_by_code
from app.db import connect, list_locations, save_obs_row
from app.importers.core import LoadedFile, load_for_crop, project_row

_SETTING_LAST_DIR = "survey_import_last_dir"


def _find_photo_index(source_csv: Path) -> dict[str, Path]:
    """Scan the source's parent folder for image files keyed by filename.

    Survey123 exports drop photos either in the same folder as the CSV or in
    a single-level subfolder (commonly `media/` or `<survey_name>/`). We
    handle both by indexing every image found within 1 level of the CSV.
    """
    parent = source_csv.parent
    if not parent.is_dir():
        return {}
    index: dict[str, Path] = {}
    # Same folder
    for p in parent.iterdir():
        if p.is_file() and p.suffix.lower() in image_storage.IMAGE_EXTS:
            index.setdefault(p.name, p)
    # One level deep
    for sub in parent.iterdir():
        if not sub.is_dir():
            continue
        for p in sub.iterdir():
            if p.is_file() and p.suffix.lower() in image_storage.IMAGE_EXTS:
                index.setdefault(p.name, p)
    return index


class SurveyImportTab(QWidget):
    def __init__(self, main_window) -> None:
        super().__init__(main_window)
        self._main = main_window
        self._loaded: LoadedFile | None = None
        self._valid_locations: set[str] = set()

        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)

        # --- File picker row ----------------------------------------------
        file_row = QHBoxLayout()
        file_row.addWidget(QLabel("Source file:"))
        self.path_label = QLabel("(none)")
        self.path_label.setStyleSheet("color: gray;")
        file_row.addWidget(self.path_label, 1)
        browse_btn = QPushButton("Browse…")
        browse_btn.clicked.connect(self._on_browse)
        file_row.addWidget(browse_btn)
        outer.addLayout(file_row)

        # --- Mapping config row -------------------------------------------
        cfg_row = QHBoxLayout()
        cfg_row.addWidget(QLabel("Source ID column:"))
        self.id_combo = QComboBox(self)
        self.id_combo.setMinimumWidth(220)
        self.id_combo.currentIndexChanged.connect(self._refresh_preview)
        cfg_row.addWidget(self.id_combo)
        cfg_row.addStretch(1)
        outer.addLayout(cfg_row)

        # --- Summary text -------------------------------------------------
        self.summary = QPlainTextEdit(self)
        self.summary.setReadOnly(True)
        self.summary.setMaximumHeight(120)
        self.summary.setPlaceholderText("Load a file to see the column-mapping summary.")
        outer.addWidget(self.summary)

        # --- Preview table ------------------------------------------------
        outer.addWidget(QLabel("Preview (rows that will be imported are highlighted):"))
        self.preview = QTableWidget(self)
        self.preview.setEditTriggers(QTableWidget.NoEditTriggers)
        self.preview.setSelectionMode(QTableWidget.NoSelection)
        outer.addWidget(self.preview, 1)

        # --- Action row ---------------------------------------------------
        action_row = QHBoxLayout()
        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color: #555;")
        action_row.addWidget(self.status_label, 1)
        self.import_btn = QPushButton("Import into current week")
        self.import_btn.setDefault(True)
        self.import_btn.setEnabled(False)
        self.import_btn.clicked.connect(self._on_import)
        action_row.addWidget(self.import_btn)
        outer.addLayout(action_row)

        main_window.context_changed.connect(self._on_context_changed)
        self._on_context_changed()

    # ---- context ----------------------------------------------------------

    def _on_context_changed(self) -> None:
        crop_code = self._main.current_crop_code()
        self._valid_locations = set()
        if crop_code:
            with connect() as conn:
                self._valid_locations = {
                    r["location_id"] for r in list_locations(conn, crop_code)
                }
        # Different crop → previous file's mapping is stale. Clear it.
        if self._loaded:
            self.summary.setPlainText(
                "Crop changed — reload the source file to re-map columns to the new crop."
            )
            self._loaded = None
            self.path_label.setText("(none)")
            self.preview.clear()
            self.preview.setRowCount(0)
            self.preview.setColumnCount(0)
            self.id_combo.clear()
        self._update_import_button()

    # ---- browse + load ----------------------------------------------------

    def _on_browse(self) -> None:
        last_dir = app_settings.get(_SETTING_LAST_DIR, "")
        path_str, _ = QFileDialog.getOpenFileName(
            self,
            "Pick Survey123 export",
            last_dir,
            "Data files (*.csv *.xlsx *.xls *.xlsm)",
        )
        if not path_str:
            return
        path = Path(path_str)
        app_settings.set_(_SETTING_LAST_DIR, str(path.parent))
        self._load(path)

    def _load(self, path: Path) -> None:
        crop_code = self._main.current_crop_code()
        if not crop_code:
            QMessageBox.information(self, "Pick a crop", "Choose a crop first.")
            return
        try:
            crop = crop_by_code(crop_code)
            loaded = load_for_crop(path, crop.template_path)
        except Exception as exc:
            QMessageBox.critical(self, "Could not read file", f"{exc}")
            return
        self._loaded = loaded
        self.path_label.setText(str(path))
        self.path_label.setStyleSheet("color: black;")

        # Populate the ID-column combo with all source columns, defaulting
        # to whichever one auto-mapped to the template's "ID".
        self.id_combo.blockSignals(True)
        self.id_combo.clear()
        default_idx = -1
        for i, col in enumerate(loaded.source_cols):
            self.id_combo.addItem(col, col)
            if loaded.mapping.matches.get(col) == "ID" and default_idx < 0:
                default_idx = i
        if default_idx < 0:
            # No template "ID" match; try common conventions.
            for i, col in enumerate(loaded.source_cols):
                if col.strip().lower() in ("id", "location", "location_id", "site"):
                    default_idx = i
                    break
        self.id_combo.setCurrentIndex(max(default_idx, 0))
        self.id_combo.blockSignals(False)

        self._render_summary()
        self._refresh_preview()
        self._update_import_button()

    # ---- summary + preview -----------------------------------------------

    def _render_summary(self) -> None:
        if self._loaded is None:
            self.summary.clear()
            return
        m = self._loaded.mapping
        lines = [
            f"Rows in file: {self._loaded.row_count}",
            f"Source columns matched to template: {len(m.matches)}",
        ]
        if m.unmatched_source:
            lines.append("")
            lines.append("Source columns ignored (no matching template column):")
            for c in m.unmatched_source:
                lines.append(f"  - {c}")
        if m.unmatched_target:
            # Limit noise — the template has many columns; only show first few.
            lines.append("")
            lines.append(
                f"Template columns not provided by source ({len(m.unmatched_target)}):"
            )
            for c in m.unmatched_target[:10]:
                lines.append(f"  - {c}")
            if len(m.unmatched_target) > 10:
                lines.append(f"  … and {len(m.unmatched_target) - 10} more")
        self.summary.setPlainText("\n".join(lines))

    def _refresh_preview(self) -> None:
        self.preview.clear()
        self.preview.setRowCount(0)
        self.preview.setColumnCount(0)
        if self._loaded is None or self.id_combo.count() == 0:
            return

        id_col = self.id_combo.currentData()
        rows = self._loaded.rows

        # Limit preview columns to a useful subset: id + key fields.
        # Show the id column first, then the first ~6 mapped columns.
        mapped_cols = [c for c in self._loaded.source_cols if c in self._loaded.mapping.matches]
        display_cols = [id_col] + [c for c in mapped_cols if c != id_col][:6]

        self.preview.setColumnCount(len(display_cols) + 1)
        headers = ["Target"] + display_cols
        self.preview.setHorizontalHeaderLabels(headers)
        self.preview.setRowCount(len(rows))
        for r, row in enumerate(rows):
            id_val = row.get(id_col, "").strip()
            target = id_val if id_val in self._valid_locations else "(skip)"
            t_item = QTableWidgetItem(target)
            if target == "(skip)":
                t_item.setForeground(Qt.gray)
            self.preview.setItem(r, 0, t_item)
            for c, col in enumerate(display_cols, start=1):
                self.preview.setItem(r, c, QTableWidgetItem(row.get(col, "")))
        self.preview.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.preview.resizeColumnsToContents()

    def _update_import_button(self) -> None:
        ready = bool(self._loaded
                     and self._main.current_crop_code()
                     and self._main.current_iso_week()
                     and self.id_combo.count() > 0)
        self.import_btn.setEnabled(ready)
        if not self._main.current_iso_week():
            self.status_label.setText("Pick or create a week first.")
        elif not self._loaded:
            self.status_label.setText("Pick a source file to start.")
        else:
            self.status_label.setText("")

    # ---- import -----------------------------------------------------------

    def _on_import(self) -> None:
        if self._loaded is None:
            return
        crop_code = self._main.current_crop_code()
        iso_week = self._main.current_iso_week()
        if not (crop_code and iso_week):
            QMessageBox.information(self, "Import", "Pick a crop and week first.")
            return
        id_col = self.id_combo.currentData()
        if not id_col:
            QMessageBox.information(self, "Import", "Pick the source ID column first.")
            return

        # Scan the source file's neighborhood for photos that match any
        # Images-column reference. If found, we'll copy them into the app's
        # image storage as part of the import.
        photo_index = _find_photo_index(self._loaded.path)
        photos_copied = 0
        photos_missing = 0

        imported = 0
        skipped_no_loc = 0
        skipped_empty = 0
        with connect() as conn:
            for row in self._loaded.rows:
                loc_id = row.get(id_col, "").strip()
                if loc_id not in self._valid_locations:
                    skipped_no_loc += 1
                    continue
                values = project_row(row, self._loaded.mapping)
                if not values:
                    skipped_empty += 1
                    continue
                # Handle Images column specially: copy referenced files
                # into image_storage and rewrite the cell with the final names.
                if "Images" in values:
                    referenced = image_storage.parse_list(values["Images"])
                    stored_names: list[str] = []
                    for name in referenced:
                        src = photo_index.get(name)
                        if src is None:
                            photos_missing += 1
                            # Still record the filename so the user can drop the
                            # file in later via the Observations tab.
                            stored_names.append(name)
                            continue
                        try:
                            stored = image_storage.attach(
                                crop_code, iso_week, loc_id, src
                            )
                            stored_names.append(stored)
                            photos_copied += 1
                        except Exception:
                            photos_missing += 1
                            stored_names.append(name)
                    values["Images"] = image_storage.format_list(stored_names)
                save_obs_row(conn, crop_code, iso_week, loc_id, values)
                imported += 1

        msg_lines = [
            f"Imported {imported} rows into {crop_code} / {iso_week}.",
            f"Skipped {skipped_no_loc} rows whose ID didn't match a known location.",
            f"Skipped {skipped_empty} rows with no mapped values.",
        ]
        if photos_copied or photos_missing:
            msg_lines.append("")
            msg_lines.append(f"Photos copied into storage: {photos_copied}.")
            if photos_missing:
                msg_lines.append(
                    f"Photo references not found near the source file: {photos_missing}. "
                    "Drop them in via the Observations tab when available."
                )
        QMessageBox.information(self, "Import complete", "\n".join(msg_lines))
        self.status_label.setText(f"Last import: {imported} rows.")
