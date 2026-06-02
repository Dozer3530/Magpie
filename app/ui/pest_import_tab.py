"""Pest ID import tab — desktop mirror of the web Pest ID view.

The Pest ID sheet is a living per-field bug log. Crop is auto-detected from the
point IDs (M = Canola, L = Corn); the user picks which sheet-week to extract and
it attaches to the app's currently-selected ISO week. No column mapping (bug
types vary) — just a week picker and an "uploaded" summary. All logic lives in
`app.services.pests`, so this stays in lockstep with the web view.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app import app_settings
from app.importers.pest import ParsedPest
from app.services import pests as pests_service

_SETTING_LAST_DIR = "pest_import_last_dir"


class PestImportTab(QWidget):
    def __init__(self, main_window) -> None:
        super().__init__(main_window)
        self._main = main_window
        self._parsed: ParsedPest | None = None
        self._path: Path | None = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)

        outer.addWidget(QLabel(
            "Pest ID is a living document — pick the sheet week to pull into the "
            "current week's package. Crop is detected from the point IDs (M/L)."
        ))

        file_row = QHBoxLayout()
        file_row.addWidget(QLabel("Pest sheet:"))
        self.path_label = QLabel("(none)")
        self.path_label.setStyleSheet("color: gray;")
        file_row.addWidget(self.path_label, 1)
        browse_btn = QPushButton("Browse…")
        browse_btn.clicked.connect(self._on_browse)
        file_row.addWidget(browse_btn)
        outer.addLayout(file_row)

        self.detected = QLabel("")
        self.detected.setStyleSheet("color: #555;")
        outer.addWidget(self.detected)

        wk_row = QHBoxLayout()
        wk_row.addWidget(QLabel("Sheet week:"))
        self.week_combo = QComboBox(self)
        self.week_combo.setMinimumWidth(360)
        self.week_combo.setEnabled(False)
        wk_row.addWidget(self.week_combo)
        wk_row.addStretch(1)
        outer.addLayout(wk_row)

        action_row = QHBoxLayout()
        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color: #555;")
        action_row.addWidget(self.status_label, 1)
        self.import_btn = QPushButton("Import into current week")
        self.import_btn.setEnabled(False)
        self.import_btn.clicked.connect(self._on_import)
        action_row.addWidget(self.import_btn)
        outer.addLayout(action_row)

        outer.addStretch(1)

        main_window.context_changed.connect(self._refresh_status)
        self._refresh_status()

    # ---- browse + load ---------------------------------------------------

    def _on_browse(self) -> None:
        last_dir = app_settings.get(_SETTING_LAST_DIR, "")
        path_str, _ = QFileDialog.getOpenFileName(
            self, "Pick Pest ID sheet", last_dir, "Data files (*.csv *.xlsx *.xls *.xlsm)"
        )
        if not path_str:
            return
        path = Path(path_str)
        app_settings.set_(_SETTING_LAST_DIR, str(path.parent))
        try:
            parsed = pests_service.prepare(path)
        except Exception as exc:
            QMessageBox.critical(self, "Could not read pest file", f"{exc}")
            return
        self._parsed = parsed
        self._path = path
        self.path_label.setText(str(path))
        self.path_label.setStyleSheet("color: black;")
        crop_disp = "Canola" if parsed.crop_code == "canola" else "Corn" if parsed.crop_code == "corn" else parsed.crop_code
        self.detected.setText(f"Detected crop: {crop_disp} · {len(parsed.weeks)} weeks in sheet")

        self.week_combo.clear()
        for w in pests_service.week_choices(parsed):
            bugs = f"{len(w['bug_types'])} bug type(s)" if w["bug_types"] else "no bugs"
            self.week_combo.addItem(
                f"#{w['index']} · {w['date']} · cards {w['cards_completed']}/{w['total']} · {bugs}",
                w["index"],
            )
        if self.week_combo.count():
            self.week_combo.setCurrentIndex(self.week_combo.count() - 1)  # latest week
        self.week_combo.setEnabled(True)
        self._update_button()

    # ---- status + import -------------------------------------------------

    def _refresh_status(self) -> None:
        self._update_button()
        crop = self._parsed.crop_code if self._parsed else self._main.current_crop_code()
        week = self._main.current_iso_week()
        if not (crop and week):
            self.status_label.setText("Pick or create a week first.")
            return
        st = pests_service.pest_status(crop, week)
        if st["uploaded"]:
            bugs = f"{len(st['bug_types'])} bug type(s)" if st["bug_types"] else "no bugs"
            self.status_label.setText(
                f"Uploaded for {week}: cards {st['cards_completed']}/{st['total_locations']} · {bugs}"
            )
        else:
            self.status_label.setText(f"No pest data uploaded for {week} yet.")

    def _update_button(self) -> None:
        self.import_btn.setEnabled(bool(self._parsed and self._main.current_iso_week()))

    def _on_import(self) -> None:
        if self._parsed is None or self._path is None:
            return
        iso_week = self._main.current_iso_week()
        if not iso_week:
            QMessageBox.information(self, "Import", "Pick or create a week first.")
            return
        week_index = self.week_combo.currentData()
        try:
            res = pests_service.commit(self._path, iso_week, week_index)
        except Exception as exc:
            QMessageBox.critical(self, "Import failed", f"{exc}")
            return
        bugs = ", ".join(res.bug_types) if res.bug_types else "no bugs"
        QMessageBox.information(
            self, "Pest import complete",
            f"Imported pest week {res.week_label} into {res.crop_code} / {iso_week}.\n"
            f"Cards completed: {res.cards_completed}/{res.imported}\n"
            f"Bug types this week: {bugs}",
        )
        self._refresh_status()
