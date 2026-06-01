"""Week-over-week soil trends — desktop mirror of the web Trends view.

Same fixed points every week, so this shows the TDR soil readings (temp,
moisture, EC) changing over time — either the field average or one point.
Reads everything from `app.services.trends`, so it stays in lockstep with the
web Trends screen (the web additionally draws line charts; here it's a
values+delta table, an accepted presentation difference).
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.services import trends as trends_service

_METRIC_ORDER = ["temp", "moisture", "ec"]
_UP = QColor("#5a8a00")    # readable lime on light Qt
_DOWN = QColor("#2f56cc")  # blue


class TrendsTab(QWidget):
    def __init__(self, main_window) -> None:
        super().__init__(main_window)
        self._main = main_window

        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)

        self.header = QLabel("Trends — week over week", self)
        self.header.setStyleSheet("font-size: 14px; font-weight: 600;")
        outer.addWidget(self.header)

        controls = QHBoxLayout()
        controls.addWidget(QLabel("Scope:"))
        self.scope = QComboBox(self)
        self.scope.setMinimumWidth(220)
        self.scope.currentIndexChanged.connect(self._refill)
        controls.addWidget(self.scope)
        controls.addStretch(1)
        outer.addLayout(controls)

        self.table = QTableWidget(0, 4, self)
        self.table.setHorizontalHeaderLabels(
            ["Week", "Soil temp °C", "Soil moisture %", "Soil EC dS/m"]
        )
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionMode(QTableWidget.NoSelection)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        outer.addWidget(self.table, 1)

        main_window.context_changed.connect(self._on_context)
        self._on_context()

    # Rebuild the scope dropdown when the crop changes (locations differ), then
    # refill the table.
    def _on_context(self) -> None:
        crop = self._main.current_crop_code()
        prev = self.scope.currentData()
        self.scope.blockSignals(True)
        self.scope.clear()
        self.scope.addItem("Field average (all points)", "")
        if crop:
            try:
                data = trends_service.soil_trends(crop, None)
                for loc in data["locations"]:
                    self.scope.addItem(loc, loc)
            except Exception:
                pass
        idx = self.scope.findData(prev)
        self.scope.setCurrentIndex(idx if idx >= 0 else 0)
        self.scope.blockSignals(False)
        self._refill()

    def _refill(self) -> None:
        crop = self._main.current_crop_code()
        if not crop:
            self.table.setRowCount(0)
            return
        loc = self.scope.currentData() or None
        data = trends_service.soil_trends(crop, loc)
        weeks = data["weeks"]
        series = data["series"]

        # newest week first
        order = list(range(len(weeks)))[::-1]
        self.table.setRowCount(len(order))
        for r, i in enumerate(order):
            self.table.setItem(r, 0, QTableWidgetItem(weeks[i]))
            for c, mkey in enumerate(_METRIC_ORDER, start=1):
                pts = series[mkey]["points"]
                v = pts[i]
                prev = next((pts[j] for j in range(i - 1, -1, -1) if pts[j] is not None), None)
                item = QTableWidgetItem(self._cell_text(v, prev))
                item.setTextAlignment(Qt.AlignCenter)
                if v is not None and prev is not None:
                    if v > prev:
                        item.setForeground(_UP)
                    elif v < prev:
                        item.setForeground(_DOWN)
                if v is None:
                    item.setForeground(Qt.gray)
                self.table.setItem(r, c, item)

    @staticmethod
    def _cell_text(v, prev) -> str:
        if v is None:
            return "—"
        if prev is None:
            return f"{v}"
        d = round(v - prev, 1)
        if d > 0:
            return f"{v}   ▲ {d}"
        if d < 0:
            return f"{v}   ▼ {abs(d)}"
        return f"{v}   – 0"
