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
import zipfile
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

from app.config import EXPORTS_DIR
from app.crops import CROPS, crop_by_code
from app.db import connect, list_locations, list_obs_for_week
from app.exporters.excel_export import export_excel, export_filename as excel_filename
from app.exporters.gpkg_export import export_gpkg, export_filename as gpkg_filename
from app.exporters.images_export import copy_week_images


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

        # Per-location status
        with connect() as conn:
            locs = list_locations(conn, crop)
            obs = {r["location_id"]: dict(r) for r in list_obs_for_week(conn, crop, week)}
        lines = []
        filled_total = 0
        for loc in locs:
            row = obs.get(loc["location_id"], {})
            filled = sum(
                1 for k, v in row.items()
                if k not in ("iso_week", "location_id") and v not in (None, "")
            )
            filled_total += filled
            lines.append(
                f"  {loc['location_id']:>3}  ({loc['lat']}, {loc['lon']})  — "
                f"{filled} fields with data" + ("" if filled else "   [blank]")
            )
        self.status_view.setPlainText(
            f"{len(locs)} locations, {sum(1 for l in locs if obs.get(l['location_id']))} "
            f"with at least one obs row.\n\n" + "\n".join(lines)
        )
        # Reset the "Open folder" button until a successful export this turn
        self.open_folder_btn.setEnabled(out_dir.exists())

    # ---- export actions -----------------------------------------------

    def _week_dir(self, iso_week: str) -> Path:
        return EXPORTS_DIR / iso_week

    def _on_export_one(self) -> None:
        crop = self._main.current_crop_code()
        week = self._main.current_iso_week()
        if not (crop and week):
            return
        produced = self._export_crop(crop, week)
        zip_path = self._zip_week(week) if produced else None
        if zip_path:
            produced.append(zip_path)
        self._show_result(week, produced)

    def _on_export_all(self) -> None:
        week = self._main.current_iso_week()
        if not week:
            return
        produced: list[Path] = []
        for crop_cfg in CROPS:
            produced.extend(self._export_crop(crop_cfg.code, week))
        zip_path = self._zip_week(week) if produced else None
        if zip_path:
            produced.append(zip_path)
        self._show_result(week, produced)

    def _export_crop(self, crop_code: str, iso_week: str) -> list[Path]:
        out_dir = self._week_dir(iso_week)
        out_dir.mkdir(parents=True, exist_ok=True)
        xlsx_path = out_dir / excel_filename(crop_code, iso_week)
        gpkg_path = out_dir / gpkg_filename(crop_code, iso_week)
        try:
            export_excel(crop_code, iso_week, xlsx_path)
            export_gpkg(crop_code, iso_week, gpkg_path)
            copy_week_images(crop_code, iso_week, out_dir)
        except Exception as exc:
            QMessageBox.critical(
                self, "Export failed",
                f"{crop_code} / {iso_week}\n\n{type(exc).__name__}: {exc}",
            )
            return []
        return [xlsx_path, gpkg_path]

    def _zip_week(self, iso_week: str) -> Path | None:
        """Bundle everything in the week folder into EarthDaily_<week>.zip.

        The zip lives next to the unzipped contents so the user can decide
        which to send and still inspect/replace anything by hand.
        """
        week_dir = self._week_dir(iso_week)
        if not week_dir.is_dir():
            return None
        zip_path = week_dir / f"EarthDaily_{iso_week}.zip"
        # Atomically write to a temp name then rename so a half-zip never
        # leaves a confusing file behind.
        tmp_path = zip_path.with_suffix(".zip.tmp")
        try:
            with zipfile.ZipFile(tmp_path, "w", zipfile.ZIP_DEFLATED) as zf:
                for path in sorted(week_dir.rglob("*")):
                    if path == zip_path or path == tmp_path:
                        continue
                    if path.is_file():
                        zf.write(path, path.relative_to(week_dir))
            if zip_path.exists():
                zip_path.unlink()
            tmp_path.rename(zip_path)
        except Exception:
            tmp_path.unlink(missing_ok=True)
            raise
        return zip_path

    def _show_result(self, iso_week: str, produced: list[Path]) -> None:
        if not produced:
            self.result_label.setText("")
            return
        lines = [f"Wrote {len(produced)} file(s) to {self._week_dir(iso_week)}:"]
        for p in produced:
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
