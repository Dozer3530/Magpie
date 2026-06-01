"""Week-over-week trends — desktop mirror of the web Trends view.

Same fixed points every week, so this shows how readings change over time —
choose a metric category (soil / disease & growth / nutrients / ratios) and a
scope (field average or one point). Reads everything from
`app.services.trends`, so it stays in lockstep with the web Trends screen (the
web additionally draws line charts; here it's a values+delta table — an
accepted presentation difference).
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
        controls.addWidget(QLabel("Show:"))
        self.category = QComboBox(self)
        for key, label in [
            ("soil", "Soil readings"),
            ("disease_growth", "Disease & growth"),
            ("nutrients", "Nutrient values"),
            ("ratios", "Nutrient ratios"),
        ]:
            self.category.addItem(label, key)
        self.category.currentIndexChanged.connect(self._refill)
        controls.addWidget(self.category)

        controls.addSpacing(16)
        controls.addWidget(QLabel("Scope:"))
        self.scope = QComboBox(self)
        self.scope.setMinimumWidth(200)
        self.scope.currentIndexChanged.connect(self._refill)
        controls.addWidget(self.scope)
        controls.addStretch(1)
        outer.addLayout(controls)

        self.table = QTableWidget(0, 1, self)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionMode(QTableWidget.NoSelection)
        self.table.verticalHeader().setVisible(False)
        outer.addWidget(self.table, 1)

        main_window.context_changed.connect(self._on_context)
        self._on_context()

    def _on_context(self) -> None:
        """Rebuild the scope dropdown when the crop changes, then refill."""
        crop = self._main.current_crop_code()
        prev = self.scope.currentData()
        self.scope.blockSignals(True)
        self.scope.clear()
        self.scope.addItem("Field average (all points)", "")
        if crop:
            try:
                for loc in trends_service.trend_series(crop, None, "soil")["locations"]:
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
            self.table.setColumnCount(1)
            return
        loc = self.scope.currentData() or None
        category = self.category.currentData() or "soil"
        data = trends_service.trend_series(crop, loc, category)
        weeks, series = data["weeks"], data["series"]

        headers = ["Week"] + [s["label"] + (f" {s['unit']}" if s["unit"] else "") for s in series]
        self.table.setColumnCount(len(headers))
        self.table.setHorizontalHeaderLabels(headers)
        mode = QHeaderView.Stretch if len(headers) <= 4 else QHeaderView.ResizeToContents
        self.table.horizontalHeader().setSectionResizeMode(mode)

        order = list(range(len(weeks)))[::-1]  # newest first
        self.table.setRowCount(len(order))
        for r, i in enumerate(order):
            self.table.setItem(r, 0, QTableWidgetItem(weeks[i]))
            for c, s in enumerate(series, start=1):
                pts = s["points"]
                v = pts[i]
                prev = next((pts[j] for j in range(i - 1, -1, -1) if pts[j] is not None), None)
                item = QTableWidgetItem(self._cell_text(v, prev))
                item.setTextAlignment(Qt.AlignCenter)
                if v is None:
                    item.setForeground(Qt.gray)
                elif prev is not None and v > prev:
                    item.setForeground(_UP)
                elif prev is not None and v < prev:
                    item.setForeground(_DOWN)
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
