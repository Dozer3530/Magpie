"""Widget for attaching/removing photos on the active (crop, week, location).

Drops into the Observations tab in place of the v1 'Images skipped' note.
Reads/writes the obs row's `Images` column as a semicolon-separated list of
filenames; copies files into the app's image storage on the side.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Callable

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app import app_settings, image_storage

_SETTING_LAST_DIR = "image_attach_last_dir"


class ImageAttachWidget(QWidget):
    """Manages the `Images` field for one obs row.

    Emits `changed` whenever the attached filename list changes; the parent
    form treats this as a hint to refresh its own Save state.
    """
    changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        # Context — set by the parent before the widget is interacted with.
        self._crop_code: str | None = None
        self._iso_week: str | None = None
        self._location_id: str | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._list = QListWidget(self)
        self._list.setMinimumHeight(80)
        layout.addWidget(self._list)

        btn_row = QHBoxLayout()
        self.attach_btn = QPushButton("+ Attach…", self)
        self.attach_btn.clicked.connect(self._on_attach)
        btn_row.addWidget(self.attach_btn)

        self.remove_btn = QPushButton("Remove", self)
        self.remove_btn.clicked.connect(self._on_remove)
        btn_row.addWidget(self.remove_btn)

        self.reveal_btn = QPushButton("Open folder", self)
        self.reveal_btn.clicked.connect(self._on_reveal)
        btn_row.addWidget(self.reveal_btn)
        btn_row.addStretch(1)
        layout.addLayout(btn_row)

        self.hint_label = QLabel("", self)
        self.hint_label.setStyleSheet("color: #888; font-size: 10px;")
        layout.addWidget(self.hint_label)

        self.set_context(None, None, None)

    # ---- context lifecycle ------------------------------------------------

    def set_context(
        self,
        crop_code: str | None,
        iso_week: str | None,
        location_id: str | None,
    ) -> None:
        """Tell the widget which obs row it's managing.

        Resets the list display and disables buttons if any are None.
        """
        self._crop_code = crop_code
        self._iso_week = iso_week
        self._location_id = location_id
        ready = bool(crop_code and iso_week and location_id)
        self.attach_btn.setEnabled(ready)
        self.remove_btn.setEnabled(ready)
        self.reveal_btn.setEnabled(ready)
        if ready:
            self.hint_label.setText(
                "Photos are saved under data/images/. The Excel export "
                "writes a clickable link in the Images column."
            )
        else:
            self.hint_label.setText("Pick a crop, week, and location to attach photos.")

    # ---- DB cell <-> widget round-trip -----------------------------------

    def get_value(self) -> str:
        """Return the `Images` cell value (semicolon-separated filenames)."""
        names = [self._list.item(i).text() for i in range(self._list.count())]
        return image_storage.format_list(names)

    def set_value(self, value: str | None) -> None:
        self._list.clear()
        for name in image_storage.parse_list(value):
            self._list.addItem(name)

    # ---- actions ---------------------------------------------------------

    def _on_attach(self) -> None:
        if not (self._crop_code and self._iso_week and self._location_id):
            return
        last_dir = app_settings.get(_SETTING_LAST_DIR, "")
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Pick photos to attach",
            last_dir,
            "Images (*.jpg *.jpeg *.png *.heic *.heif *.webp *.tif *.tiff *.bmp);;All files (*)",
        )
        if not paths:
            return
        app_settings.set_(_SETTING_LAST_DIR, str(Path(paths[0]).parent))
        added: list[str] = []
        errs: list[str] = []
        for p in paths:
            try:
                final_name = image_storage.attach(
                    self._crop_code, self._iso_week, self._location_id, Path(p)
                )
                added.append(final_name)
            except Exception as exc:
                errs.append(f"{Path(p).name}: {exc}")
        for name in added:
            # Don't duplicate filenames already in the list (e.g. if user re-attaches).
            if not self._list.findItems(name, 0):
                self._list.addItem(name)
        if errs:
            QMessageBox.warning(self, "Some photos failed", "\n".join(errs))
        if added:
            self.changed.emit()

    def _on_remove(self) -> None:
        item = self._list.currentItem()
        if item is None:
            return
        if not (self._crop_code and self._iso_week and self._location_id):
            return
        name = item.text()
        confirm = QMessageBox.question(
            self,
            "Remove photo",
            f"Remove '{name}' from this record and delete the file?",
        )
        if confirm != QMessageBox.Yes:
            return
        image_storage.remove(self._crop_code, self._iso_week, self._location_id, name)
        self._list.takeItem(self._list.row(item))
        self.changed.emit()

    def _on_reveal(self) -> None:
        if not (self._crop_code and self._iso_week and self._location_id):
            return
        folder = image_storage.location_dir(
            self._crop_code, self._iso_week, self._location_id
        )
        folder.mkdir(parents=True, exist_ok=True)
        if sys.platform == "win32":
            os.startfile(folder)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(folder)])
        else:
            subprocess.Popen(["xdg-open", str(folder)])
