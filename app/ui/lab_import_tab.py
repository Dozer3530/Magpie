"""Lab import tab.

Lab reports map manually to locations — one report per location, but some
weeks skip locations entirely. The UI shows the source rows and lets the
user pick a target location (or `(skip)`) per row via dropdowns.

Columns auto-map to template fields by name; only mapped non-empty cells
are written, so lab imports won't clobber unrelated columns (TDR readings,
disease observations, etc.) that come from Survey123 or manual entry.
"""
from __future__ import annotations

from pathlib import Path

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

from app import app_settings
from app.importers.core import LoadedFile
from app.services import imports as imports_service
from app.services.imports import DuplicateTargetError

_SETTING_LAST_DIR = "lab_import_last_dir"
_SKIP = "(skip)"


class LabImportTab(QWidget):
    def __init__(self, main_window) -> None:
        super().__init__(main_window)
        self._main = main_window
        self._loaded: LoadedFile | None = None
        self._location_ids: list[str] = []
        self._row_combos: list[QComboBox] = []

        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)

        # --- File picker --------------------------------------------------
        file_row = QHBoxLayout()
        file_row.addWidget(QLabel("Source file:"))
        self.path_label = QLabel("(none)")
        self.path_label.setStyleSheet("color: gray;")
        file_row.addWidget(self.path_label, 1)
        browse_btn = QPushButton("Browse…")
        browse_btn.clicked.connect(self._on_browse)
        file_row.addWidget(browse_btn)
        outer.addLayout(file_row)

        # --- Summary ------------------------------------------------------
        self.summary = QPlainTextEdit(self)
        self.summary.setReadOnly(True)
        self.summary.setMaximumHeight(120)
        self.summary.setPlaceholderText("Load a lab file to see the column-mapping summary.")
        outer.addWidget(self.summary)

        # --- Mapping table ------------------------------------------------
        outer.addWidget(QLabel("Pick the target location for each lab row (rows set to (skip) are ignored):"))
        self.table = QTableWidget(self)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        outer.addWidget(self.table, 1)

        # --- Action -------------------------------------------------------
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
        self._location_ids = []
        if crop_code:
            self._location_ids = sorted(imports_service.valid_locations(crop_code))
        if self._loaded:
            self.summary.setPlainText(
                "Crop changed — reload the lab file to re-map columns to the new crop."
            )
            self._loaded = None
            self.path_label.setText("(none)")
            self.table.clear()
            self.table.setRowCount(0)
            self.table.setColumnCount(0)
            self._row_combos = []
        self._update_import_button()

    # ---- browse + load ---------------------------------------------------

    def _on_browse(self) -> None:
        last_dir = app_settings.get(_SETTING_LAST_DIR, "")
        path_str, _ = QFileDialog.getOpenFileName(
            self,
            "Pick lab report file",
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
            loaded = imports_service.prepare(path, crop_code)
        except Exception as exc:
            QMessageBox.critical(self, "Could not read file", f"{exc}")
            return
        self._loaded = loaded
        self.path_label.setText(str(path))
        self.path_label.setStyleSheet("color: black;")
        self._render_summary()
        self._populate_table()
        self._update_import_button()

    # ---- summary ---------------------------------------------------------

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
        self.summary.setPlainText("\n".join(lines))

    # ---- table -----------------------------------------------------------

    def _populate_table(self) -> None:
        self.table.clear()
        self._row_combos = []
        if self._loaded is None:
            return

        rows = self._loaded.rows
        # Show the columns most useful for picking a target location.
        # SampleID is usually the descriptive name (e.g. "Point 4 Good"),
        # followed by ReportDate, ReportNo, LabNo, then any mapped columns.
        # SampleID + LabNo + ReportDate aren't in the template (so not in
        # `mapping.matches`) but are still useful for the human picker, so
        # we include them from source_cols directly.
        priority_lc = ("sampleid", "reportdate", "reportno", "labno",
                       "lab_no.", "lab_no")
        priority = [c for c in self._loaded.source_cols
                    if c.strip().lower() in priority_lc]
        mapped_cols = [c for c in self._loaded.source_cols
                       if c in self._loaded.mapping.matches]
        rest = [c for c in mapped_cols if c not in priority][:6]
        display_cols: list[str] = priority + rest

        self.table.setColumnCount(len(display_cols) + 1)
        self.table.setHorizontalHeaderLabels(["Target location"] + display_cols)
        self.table.setRowCount(len(rows))

        # Heuristic pre-fill: if the source has an `ID`-like column whose
        # values look like our location_ids, pre-select them.
        id_col = self._guess_id_column()

        for r, row in enumerate(rows):
            combo = QComboBox(self.table)
            combo.addItem(_SKIP, "")
            for loc_id in self._location_ids:
                combo.addItem(loc_id, loc_id)
            if id_col is not None:
                guess = row.get(id_col, "").strip()
                if guess in self._location_ids:
                    combo.setCurrentText(guess)
            self.table.setCellWidget(r, 0, combo)
            self._row_combos.append(combo)
            for c, col in enumerate(display_cols, start=1):
                self.table.setItem(r, c, QTableWidgetItem(row.get(col, "")))
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.table.resizeColumnsToContents()

    def _guess_id_column(self) -> str | None:
        if self._loaded is None:
            return None
        for col in self._loaded.source_cols:
            if col.strip().lower() in ("id", "location", "location_id", "site"):
                return col
        return None

    def _update_import_button(self) -> None:
        ready = bool(self._loaded
                     and self._main.current_crop_code()
                     and self._main.current_iso_week())
        self.import_btn.setEnabled(ready)
        if not self._main.current_iso_week():
            self.status_label.setText("Pick or create a week first.")
        elif not self._loaded:
            self.status_label.setText("Pick a source file to start.")
        else:
            self.status_label.setText("")

    # ---- import ----------------------------------------------------------

    def _on_import(self) -> None:
        if self._loaded is None:
            return
        crop_code = self._main.current_crop_code()
        iso_week = self._main.current_iso_week()
        if not (crop_code and iso_week):
            QMessageBox.information(self, "Import", "Pick a crop and week first.")
            return

        # Per-row target assignment from the dropdowns; the service validates
        # one-to-one and commits.
        row_targets = {
            r: combo.currentData()
            for r, combo in enumerate(self._row_combos)
            if combo.currentData()
        }
        try:
            res = imports_service.commit_lab(self._loaded, crop_code, iso_week, row_targets)
        except DuplicateTargetError as exc:
            QMessageBox.warning(self, "Duplicate target location", str(exc))
            return

        msg = (
            f"Imported {res.imported} lab rows into {crop_code} / {iso_week}.\n"
            f"Skipped {res.skipped_no_target} rows set to (skip).\n"
            f"Skipped {res.skipped_empty} rows with no mapped values."
        )
        QMessageBox.information(self, "Import complete", msg)
        self.status_label.setText(f"Last import: {res.imported} rows.")
