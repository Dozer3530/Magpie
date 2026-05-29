"""Weekly export tab.

Produces the four-file weekly package the client expects:

    exports/<YYYY-Www>/
        Canola_<YYYY-Www>.xlsx
        Canola_<YYYY-Www>.gpkg
        Corn_<YYYY-Www>.xlsx
        Corn_<YYYY-Www>.gpkg

Excel is template-stamped (preserves header styling). GPKG is a Point layer
keyed on the fixed monitoring locations.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from app.crops import crop_by_code
from app.services import exports as exports_service
from app.services.exports import ExportResult


class ExportTab(QWidget):
    def __init__(self, main_window) -> None:
        super().__init__(main_window)
        self._main = main_window

        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)

        # --- Header summary ----------------------------------------------
        self.header = QLabel("(no crop / week selected)", self)
        self.header.setStyleSheet("font-size: 14px;")
        outer.addWidget(self.header)

        # --- Per-location status report ----------------------------------
        outer.addWidget(QLabel("Location status (for the current crop + week):"))
        self.status_view = QPlainTextEdit(self)
        self.status_view.setReadOnly(True)
        outer.addWidget(self.status_view, 1)

        # --- Action row --------------------------------------------------
        actions = QHBoxLayout()
        self.export_one_btn = QPushButton("Export this crop", self)
        self.export_one_btn.setDefault(True)
        self.export_one_btn.clicked.connect(self._on_export_one)
        actions.addWidget(self.export_one_btn)

        self.export_all_btn = QPushButton("Export all crops for this week", self)
        self.export_all_btn.clicked.connect(self._on_export_all)
        actions.addWidget(self.export_all_btn)

        actions.addStretch(1)
        self.open_folder_btn = QPushButton("Open week folder", self)
        self.open_folder_btn.setEnabled(False)
        self.open_folder_btn.clicked.connect(self._on_open_folder)
        actions.addWidget(self.open_folder_btn)
        outer.addLayout(actions)

        # --- Result log --------------------------------------------------
        outer.addWidget(self._hr())
        self.result_label = QLabel("", self)
        self.result_label.setWordWrap(True)
        outer.addWidget(self.result_label)

        main_window.context_changed.connect(self._refresh)
        self._refresh()

    @staticmethod
    def _hr() -> QFrame:
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        return line

    # ---- context refresh ----------------------------------------------

    def _refresh(self) -> None:
        crop = self._main.current_crop_code()
        week = self._main.current_iso_week()
        if not (crop and week):
            self.header.setText("Pick a crop and week to enable export.")
            self.export_one_btn.setEnabled(False)
            self.export_all_btn.setEnabled(False)
            self.status_view.clear()
            return

        crop_cfg = crop_by_code(crop)
        out_dir = self._week_dir(week)
        self.header.setText(
            f"{crop_cfg.display_name} — week {week}\n"
            f"Output folder: {out_dir}"
        )
        self.export_one_btn.setEnabled(True)
        self.export_all_btn.setEnabled(True)

        # Per-location status (computed by the shared service).
        status = exports_service.week_status(crop, week)
        lines = []
        for loc in status.locations:
            lines.append(
                f"  {loc.location_id:>3}  ({loc.lat}, {loc.lon})  — "
                f"{loc.filled} fields with data" + ("" if loc.filled else "   [blank]")
            )
        self.status_view.setPlainText(
            f"{status.total_locations} locations, {status.locations_with_data} "
            f"with at least one obs row.\n\n" + "\n".join(lines)
        )
        # Reset the "Open folder" button until a successful export this turn
        self.open_folder_btn.setEnabled(out_dir.exists())

    # ---- export actions -----------------------------------------------

    def _week_dir(self, iso_week: str) -> Path:
        return exports_service.week_dir(iso_week)

    def _on_export_one(self) -> None:
        crop = self._main.current_crop_code()
        week = self._main.current_iso_week()
        if not (crop and week):
            return
        self._show_result(exports_service.build_week_package(crop, week))

    def _on_export_all(self) -> None:
        week = self._main.current_iso_week()
        if not week:
            return
        self._show_result(exports_service.build_all(week))

    def _show_result(self, result: ExportResult) -> None:
        for crop_code, message in result.errors:
            QMessageBox.critical(
                self, "Export failed", f"{crop_code} / {result.week}\n\n{message}"
            )
        if not result.produced:
            self.result_label.setText("")
            return
        lines = [f"Wrote {len(result.produced)} file(s) to {self._week_dir(result.week)}:"]
        for p in result.produced:
            lines.append(f"  • {p.name}")
        self.result_label.setText("\n".join(lines))
        self.open_folder_btn.setEnabled(True)

    def _on_open_folder(self) -> None:
        week = self._main.current_iso_week()
        if not week:
            return
        target = self._week_dir(week)
        if not target.exists():
            QMessageBox.information(self, "Open folder", "Folder doesn't exist yet — export first.")
            return
        if sys.platform == "win32":
            os.startfile(target)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(target)])
        else:
            subprocess.Popen(["xdg-open", str(target)])
