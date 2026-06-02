"""At-a-glance view of how complete the current week is across every crop.

Shows one table per crop: for each fixed monitoring location, the number of
template fields that have a value. Useful for spotting gaps before exporting
(e.g. surveyor missed M4 this week, lab report not in yet, etc.).
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.crops import CROPS
from app.services import exports as exports_service
from app.services import pests as pests_service


class WeekOverviewTab(QWidget):
    def __init__(self, main_window) -> None:
        super().__init__(main_window)
        self._main = main_window

        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)

        self.header = QLabel("Week overview", self)
        self.header.setStyleSheet("font-size: 14px;")
        outer.addWidget(self.header)

        # One table per crop, side-by-side.
        self._crop_tables: dict[str, QTableWidget] = {}
        self._totals_labels: dict[str, QLabel] = {}
        self._pest_labels: dict[str, QLabel] = {}
        crops_row = QHBoxLayout()
        for crop in CROPS:
            box = QGroupBox(crop.display_name, self)
            vbox = QVBoxLayout(box)
            table = QTableWidget(0, 3, box)
            table.setHorizontalHeaderLabels(["Location", "Fields with data", "Total expected"])
            table.setEditTriggers(QTableWidget.NoEditTriggers)
            table.setSelectionMode(QTableWidget.NoSelection)
            table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
            table.verticalHeader().setVisible(False)
            vbox.addWidget(table, 1)
            totals = QLabel("", box)
            totals.setStyleSheet("color: #555;")
            vbox.addWidget(totals)
            pest = QLabel("", box)
            pest.setStyleSheet("color: #2f6e2f;")
            pest.setWordWrap(True)
            vbox.addWidget(pest)
            self._crop_tables[crop.code] = table
            self._totals_labels[crop.code] = totals
            self._pest_labels[crop.code] = pest
            crops_row.addWidget(box, 1)
        outer.addLayout(crops_row, 1)

        main_window.context_changed.connect(self._refresh)
        self._refresh()

    def _refresh(self) -> None:
        week = self._main.current_iso_week()
        if not week:
            self.header.setText("Pick a week to see the overview.")
            for t in self._crop_tables.values():
                t.setRowCount(0)
            for lbl in self._totals_labels.values():
                lbl.setText("")
            for lbl in self._pest_labels.values():
                lbl.setText("")
            return
        self.header.setText(f"Week overview — {week}")

        for crop in CROPS:
            table = self._crop_tables[crop.code]
            totals = self._totals_labels[crop.code]
            status = exports_service.week_status(crop.code, week)
            expected = status.expected_fields
            locs = status.locations

            table.setRowCount(len(locs))
            total_fields_filled = 0
            for r, loc in enumerate(locs):
                filled = loc.filled
                total_fields_filled += filled
                table.setItem(r, 0, QTableWidgetItem(loc.location_id))
                fill_item = QTableWidgetItem(str(filled))
                fill_item.setTextAlignment(Qt.AlignCenter)
                if filled == 0:
                    fill_item.setForeground(Qt.gray)
                table.setItem(r, 1, fill_item)
                exp_item = QTableWidgetItem(str(expected))
                exp_item.setTextAlignment(Qt.AlignCenter)
                exp_item.setForeground(Qt.gray)
                table.setItem(r, 2, exp_item)

            pct = (total_fields_filled / (expected * len(locs)) * 100) if locs and expected else 0
            totals.setText(
                f"{status.locations_with_data} / {len(locs)} locations have data — "
                f"{total_fields_filled} / {expected * len(locs)} fields filled "
                f"({pct:.0f}%)"
            )

            pest = pests_service.pest_status(crop.code, week)
            pest_lbl = self._pest_labels[crop.code]
            if pest["uploaded"]:
                bugs = (f"{len(pest['bug_types'])} bug type(s)"
                        if pest["bug_types"] else "no bugs")
                pest_lbl.setText(
                    f"Pest ID: uploaded ✓ — cards {pest['cards_completed']}/{pest['total_locations']} · {bugs}"
                )
            else:
                pest_lbl.setText("Pest ID: not uploaded")
