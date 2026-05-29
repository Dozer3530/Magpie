"""Main window: crop + week selectors at the top, feature tabs below.

The selectors emit `context_changed` whenever the active (crop_code, iso_week)
pair changes. Tabs subscribe and re-render themselves.
"""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app.db import connect, list_crops
from app.services import weeks as weeks_service
from app.ui.export_tab import ExportTab
from app.ui.lab_import_tab import LabImportTab
from app.ui.observations_tab import ObservationsTab
from app.ui.survey_import_tab import SurveyImportTab
from app.ui.week_overview_tab import WeekOverviewTab


class MainWindow(QMainWindow):
    context_changed = Signal()  # fired when crop or week selection changes

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Earth Daily Package Organizer and Creator")
        self.resize(1100, 750)

        root = QWidget(self)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(8, 8, 8, 8)
        self.setCentralWidget(root)

        layout.addLayout(self._build_context_bar())

        self.tabs = QTabWidget(self)
        self.overview_tab = WeekOverviewTab(self)
        self.obs_tab = ObservationsTab(self)
        self.survey_tab = SurveyImportTab(self)
        self.lab_tab = LabImportTab(self)
        self.export_tab = ExportTab(self)
        self.tabs.addTab(self.overview_tab, "Week overview")
        self.tabs.addTab(self.obs_tab, "Observations")
        self.tabs.addTab(self.survey_tab, "Survey123 Import")
        self.tabs.addTab(self.lab_tab, "Lab Import")
        self.tabs.addTab(self.export_tab, "Export")
        layout.addWidget(self.tabs, 1)

        self._populate_crop_combo()
        self._auto_create_current_week_if_empty()
        self._populate_week_combo()
        # Initial broadcast so the observations tab builds its form.
        self.context_changed.emit()

    def _auto_create_current_week_if_empty(self) -> None:
        """First-launch convenience: if no weeks exist, seed the current ISO week."""
        weeks_service.ensure_current_week()

    # ---- top bar ------------------------------------------------------------

    def _build_context_bar(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.addWidget(QLabel("Crop:"))
        self.crop_combo = QComboBox(self)
        self.crop_combo.currentIndexChanged.connect(self._on_context_changed)
        row.addWidget(self.crop_combo)

        row.addSpacing(16)
        row.addWidget(QLabel("Week:"))
        self.week_combo = QComboBox(self)
        self.week_combo.setMinimumWidth(160)
        self.week_combo.currentIndexChanged.connect(self._on_context_changed)
        row.addWidget(self.week_combo)

        new_week_btn = QPushButton("+ New week", self)
        new_week_btn.clicked.connect(self._on_new_week_clicked)
        row.addWidget(new_week_btn)

        delete_week_btn = QPushButton("Delete week", self)
        delete_week_btn.clicked.connect(self._on_delete_week_clicked)
        row.addWidget(delete_week_btn)

        row.addStretch(1)
        return row

    def _populate_crop_combo(self) -> None:
        self.crop_combo.blockSignals(True)
        self.crop_combo.clear()
        with connect() as conn:
            for crop in list_crops(conn):
                self.crop_combo.addItem(crop["display_name"], crop["code"])
        self.crop_combo.blockSignals(False)

    def _populate_week_combo(self, prefer: str | None = None) -> None:
        self.week_combo.blockSignals(True)
        self.week_combo.clear()
        for w in weeks_service.list_week_rows():
            label = w["iso_week"] + (f" — {w['label']}" if w["label"] else "")
            self.week_combo.addItem(label, w["iso_week"])
        if prefer:
            idx = self.week_combo.findData(prefer)
            if idx >= 0:
                self.week_combo.setCurrentIndex(idx)
        self.week_combo.blockSignals(False)

    def _on_delete_week_clicked(self) -> None:
        week = self.current_iso_week()
        if not week:
            return
        confirm = QMessageBox.question(
            self,
            "Delete week",
            f"Delete week {week} and all observation rows for every crop?\n\n"
            f"This cannot be undone.",
            QMessageBox.Yes | QMessageBox.Cancel,
            QMessageBox.Cancel,
        )
        if confirm != QMessageBox.Yes:
            return
        try:
            weeks_service.delete_week(week)
        except Exception as exc:
            QMessageBox.critical(self, "Delete failed", str(exc))
            return
        self._populate_week_combo()
        self._on_context_changed()

    def _on_new_week_clicked(self) -> None:
        default = weeks_service.current_iso_week()
        text, ok = QInputDialog.getText(
            self,
            "New week",
            "ISO week tag (e.g. 2026-W21):",
            text=default,
        )
        if not ok:
            return
        tag = text.strip()
        if not tag:
            return
        try:
            weeks_service.create_week(tag)
        except Exception as exc:
            QMessageBox.warning(self, "Could not create week", str(exc))
            return
        self._populate_week_combo(prefer=tag)
        # currentIndexChanged didn't fire because we blocked signals on populate
        self._on_context_changed()

    def _on_context_changed(self) -> None:
        self.context_changed.emit()

    # ---- public accessors used by tabs -------------------------------------

    def current_crop_code(self) -> str | None:
        return self.crop_combo.currentData()

    def current_iso_week(self) -> str | None:
        return self.week_combo.currentData()

