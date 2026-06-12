"""Reactive import tab — desktop mirror of the web Reactive view.

Pulls the client-scattered "reactive" points (fields other than the fixed
Field 17 / Field 18) out of the same cumulative scouting export. Each point
keeps its own GPS and is numbered per field (F1, F2…), continuing across weeks.
Survey123 data only. All logic lives in `app.services.reactive`.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app import app_settings
from app.services import reactive as reactive_service

_SETTING_LAST_DIR = "survey_import_last_dir"  # shared with the scouting tab
_OK = QColor("#5a8a00")


class ReactiveImportTab(QWidget):
    def __init__(self, main_window) -> None:
        super().__init__(main_window)
        self._main = main_window
        self._path: Path | None = None
        self._prep: dict | None = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)

        outer.addWidget(QLabel(
            "Upload the same scouting export. This pulls the scattered REACTIVE "
            "points (fields other than the fixed Field 17 / Field 18) — each "
            "keeps its own GPS and is numbered per field (F1, F2…), continuing "
            "across weeks. Importing fills BOTH crops for the selected week."
        ))

        file_row = QHBoxLayout()
        file_row.addWidget(QLabel("Scouting file:"))
        self.path_label = QLabel("(none)")
        self.path_label.setStyleSheet("color: gray;")
        file_row.addWidget(self.path_label, 1)
        browse_btn = QPushButton("Browse…")
        browse_btn.clicked.connect(self._on_browse)
        file_row.addWidget(browse_btn)
        outer.addLayout(file_row)

        ev_row = QHBoxLayout()
        ev_row.addWidget(QLabel("Scouting event:"))
        self.event_combo = QComboBox(self)
        self.event_combo.setMinimumWidth(420)
        self.event_combo.setEnabled(False)
        self.event_combo.currentIndexChanged.connect(self._refill_table)
        ev_row.addWidget(self.event_combo)
        ev_row.addStretch(1)
        outer.addLayout(ev_row)

        outer.addWidget(QLabel("Reactive points (what Import will write):"))
        self.table = QTableWidget(0, 6, self)
        self.table.setHorizontalHeaderLabels(
            ["Time", "Field", "Crop", "Point", "Lat / Lon", "Scouter"]
        )
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionMode(QTableWidget.NoSelection)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table.verticalHeader().setVisible(False)
        outer.addWidget(self.table, 1)

        action_row = QHBoxLayout()
        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color: #555;")
        action_row.addWidget(self.status_label, 1)
        self.import_btn = QPushButton("Import into current week")
        self.import_btn.setEnabled(False)
        self.import_btn.clicked.connect(self._on_import)
        action_row.addWidget(self.import_btn)
        outer.addLayout(action_row)

        main_window.context_changed.connect(self._update_button)
        self._update_button()

    # ---- browse + load ---------------------------------------------------

    def _on_browse(self) -> None:
        last_dir = app_settings.get(_SETTING_LAST_DIR, "")
        path_str, _ = QFileDialog.getOpenFileName(
            self, "Pick scouting export", last_dir, "Data files (*.csv *.xlsx *.xls *.xlsm)"
        )
        if not path_str:
            return
        path = Path(path_str)
        app_settings.set_(_SETTING_LAST_DIR, str(path.parent))
        try:
            prep = reactive_service.prepare(path)
        except Exception as exc:
            QMessageBox.critical(self, "Could not read scouting file", f"{exc}")
            return
        events = [e for e in prep["events"] if e["n_rows"]]
        if not events:
            QMessageBox.warning(
                self, "No reactive points",
                "No reactive points in that file (every row is a fixed home field)."
            )
            return
        self._path = path
        self._prep = prep
        self.path_label.setText(str(path))
        self.path_label.setStyleSheet("color: black;")

        self.event_combo.blockSignals(True)
        self.event_combo.clear()
        for ev in events:
            crops = " / ".join(f"{n} {c.capitalize()}" for c, n in ev["crop_counts"].items()) or "no points"
            fields = ", ".join(ev.get("fields", [])) or "—"
            self.event_combo.addItem(
                f"{ev['date']} · {ev['n_rows']} reactive · {crops} · {fields}", ev["date"]
            )
        self.event_combo.setCurrentIndex(self.event_combo.count() - 1)  # newest
        self.event_combo.setEnabled(True)
        self.event_combo.blockSignals(False)
        self._refill_table()
        self._update_button()

    # ---- preview table -----------------------------------------------------

    def _current_event(self) -> dict | None:
        if not self._prep:
            return None
        date = self.event_combo.currentData()
        for ev in self._prep["events"]:
            if ev["date"] == date:
                return ev
        return None

    def _refill_table(self) -> None:
        ev = self._current_event()
        self.table.setRowCount(0)
        if ev is None:
            return
        rows = ev["assignments"]
        self.table.setRowCount(len(rows))
        for r, a in enumerate(rows):
            cells = [
                a["time"],
                a["field"],
                (a["crop"] or "?").capitalize(),
                a["point"],
                f"{a['lat']}, {a['lon']}",
                a["scouter"] or "",
            ]
            for c, text in enumerate(cells):
                item = QTableWidgetItem(text)
                item.setTextAlignment(Qt.AlignCenter if c in (0, 3) else Qt.AlignLeft | Qt.AlignVCenter)
                if c == 3:
                    item.setForeground(_OK)
                self.table.setItem(r, c, item)
        self.status_label.setText(f"{len(rows)} reactive point(s) will be written.")

    def _update_button(self) -> None:
        self.import_btn.setEnabled(bool(self._prep and self._main.current_iso_week()))
        if not self._main.current_iso_week():
            self.status_label.setText("Pick or create a week first.")

    # ---- import ------------------------------------------------------------

    def _on_import(self) -> None:
        ev = self._current_event()
        iso_week = self._main.current_iso_week()
        if ev is None or not iso_week or self._path is None:
            return
        try:
            res = reactive_service.commit(self._path, iso_week, ev["date"])
        except Exception as exc:
            QMessageBox.critical(self, "Import failed", f"{exc}")
            return
        per = ", ".join(f"{c.capitalize()}: {n}" for c, n in res["imported"].items()) or "nothing"
        lines = [f"Reactive {res['date']} → {iso_week}", f"Imported {per}."]
        if res["fields"]:
            lines.append("Fields: " + ", ".join(res["fields"]))
        if res["skipped"]:
            lines.append(f"{len(res['skipped'])} row(s) skipped (no crop / no coords).")
        if res["unmapped_columns"]:
            lines.append("Unmapped columns: " + ", ".join(res["unmapped_columns"]))
        QMessageBox.information(self, "Reactive import complete", "\n".join(lines))
        self.status_label.setText(f"Last import: {per} into {iso_week}.")
