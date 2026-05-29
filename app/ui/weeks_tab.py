"""Multi-week dashboard — desktop mirror of the web Weeks view.

Field observations (Survey123) land early each week; lab results (PT2R) lag,
so every week shows two independent completeness tracks per crop. From here you
can open, rename (changes the week's code), delete, or create a week. All real
logic lives in `app.services.weeks`, so this stays in lockstep with the web
Weeks dashboard.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app.services import weeks as weeks_service

_FIELD_COLOR = "#7E9A1E"  # lime-deep (Survey123)
_LAB_COLOR = "#3D6BFF"    # blue (PT2R)


class WeeksTab(QWidget):
    def __init__(self, main_window) -> None:
        super().__init__(main_window)
        self._main = main_window

        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)

        top = QHBoxLayout()
        self.header = QLabel("Weeks", self)
        self.header.setStyleSheet("font-size: 14px; font-weight: 600;")
        top.addWidget(self.header)
        top.addStretch(1)
        new_btn = QPushButton("+ New week", self)
        new_btn.clicked.connect(self._on_new_week)
        top.addWidget(new_btn)
        outer.addLayout(top)

        hint = QLabel(
            "Field = Survey123 · Lab = PT2R. Each bar counts monitoring points "
            "with data. Obs land first; the Lab bar fills as results come back.",
            self,
        )
        hint.setStyleSheet("color: #666;")
        hint.setWordWrap(True)
        outer.addWidget(hint)

        self._scroll = QScrollArea(self)
        self._scroll.setWidgetResizable(True)
        self._cards_host = QWidget()
        self._cards_layout = QVBoxLayout(self._cards_host)
        self._cards_layout.setAlignment(Qt.AlignTop)
        self._scroll.setWidget(self._cards_host)
        outer.addWidget(self._scroll, 1)

        main_window.context_changed.connect(self._refresh)
        self._refresh()

    # ---- rendering ---------------------------------------------------------

    def _clear_cards(self) -> None:
        while self._cards_layout.count():
            item = self._cards_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

    def _refresh(self) -> None:
        self._clear_cards()
        progress = weeks_service.all_weeks_progress()
        active = self._main.current_iso_week()
        if not progress:
            self._cards_layout.addWidget(QLabel("No weeks yet — create one to start."))
            return
        for wk in progress:
            self._cards_layout.addWidget(self._make_card(wk, active))

    def _make_card(self, wk: dict, active: str | None) -> QFrame:
        iso = wk["iso_week"]
        is_active = iso == active
        box = QFrame()
        box.setFrameShape(QFrame.StyledPanel)
        if is_active:
            box.setStyleSheet("QFrame { border: 2px solid #6f9d00; border-radius: 6px; }")
        v = QVBoxLayout(box)

        head = QHBoxLayout()
        title = QLabel(f"<b>{iso}</b>" + ("  ·  active" if is_active else ""))
        title.setStyleSheet("font-size: 13px;")
        head.addWidget(title)
        head.addStretch(1)
        open_b = QPushButton("Open")
        open_b.clicked.connect(lambda _=False, t=iso: self._main.select_week(t))
        ren_b = QPushButton("Rename")
        ren_b.clicked.connect(lambda _=False, t=iso: self._on_rename(t))
        del_b = QPushButton("Delete")
        del_b.clicked.connect(lambda _=False, t=iso: self._on_delete(t))
        for b in (open_b, ren_b, del_b):
            head.addWidget(b)
        v.addLayout(head)

        for crop in wk["crops"]:
            v.addWidget(self._crop_block(crop))
        return box

    def _crop_block(self, c: dict) -> QWidget:
        w = QWidget()
        g = QGridLayout(w)
        g.setContentsMargins(6, 2, 6, 6)
        g.setColumnStretch(1, 1)
        name = QLabel(f"<b>{c['display_name']}</b>")
        g.addWidget(name, 0, 0, 1, 2)
        total = c["total_locations"] or 1
        g.addWidget(QLabel("Field"), 1, 0)
        g.addWidget(self._bar(c["field_locations"], total, _FIELD_COLOR), 1, 1)
        g.addWidget(QLabel("Lab"), 2, 0)
        g.addWidget(self._bar(c["lab_locations"], total, _LAB_COLOR), 2, 1)
        return w

    def _bar(self, locs: int, total: int, color: str) -> QProgressBar:
        bar = QProgressBar()
        bar.setMaximum(total)
        bar.setValue(locs)
        bar.setFormat(f"{locs}/{total}")
        bar.setTextVisible(True)
        bar.setFixedHeight(18)
        bar.setStyleSheet(
            "QProgressBar { border: 1px solid #999; border-radius: 0; "
            "text-align: center; background: #f0f0f0; } "
            f"QProgressBar::chunk {{ background: {color}; }}"
        )
        return bar

    # ---- actions (delegate to the shared service) --------------------------

    def _on_new_week(self) -> None:
        self._main.create_week_interactive()

    def _on_rename(self, iso: str) -> None:
        new, ok = QInputDialog.getText(self, "Rename week", f"New name for {iso}:", text=iso)
        if not ok:
            return
        try:
            new_tag = weeks_service.rename_week(iso, new)
        except ValueError as exc:
            QMessageBox.warning(self, "Can't rename week", str(exc))
            return
        except Exception as exc:  # pragma: no cover - defensive
            QMessageBox.critical(self, "Rename failed", str(exc))
            return
        prefer = new_tag if self._main.current_iso_week() == iso else None
        self._main.refresh_weeks(prefer=prefer)

    def _on_delete(self, iso: str) -> None:
        confirm = QMessageBox.question(
            self,
            "Delete week",
            f"Delete week {iso} and all observation rows for every crop?\n\n"
            f"This cannot be undone.",
            QMessageBox.Yes | QMessageBox.Cancel,
            QMessageBox.Cancel,
        )
        if confirm != QMessageBox.Yes:
            return
        try:
            weeks_service.delete_week(iso)
        except Exception as exc:  # pragma: no cover - defensive
            QMessageBox.critical(self, "Delete failed", str(exc))
            return
        self._main.refresh_weeks()
