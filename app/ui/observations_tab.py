"""Per-(week, location) observation editor.

Builds itself from the active crop's template fields. Sections:

    Header        Date_Time + Growth stage
    Soil          TDR_1/2/3 × (TEMPERATURE, EC, MOISTURE)
    Diseases      table of (Disease | Presence yes/blank | Severity Low/Med/High)
    Insects       Insect_Damage, Insect_Identification, plus Lab_No. /
                  Disease_Report_Results when present (corn)
    Petal test    canola only
    Lab report    ReportNo + table of (Nutrient | Value | Rate)
    Ratios        table of (Ratio | Actual | Expected)
    Images        v1 placeholder (skipped)

Values are stored verbatim as TEXT in `obs_<crop>` so exports round-trip
the templates byte-equivalent.
"""
from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtGui import QDoubleValidator
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app.db import connect, list_locations
from app.schema import Field, FieldKind
from app.services import observations as obs_service
from app.ui.image_attach_widget import ImageAttachWidget


# ---- Widget binding --------------------------------------------------------

@dataclass
class FieldBinding:
    """One field + its widget. Read/write text values transparently."""
    field: Field
    widget: QWidget

    def get_value(self) -> str:
        w = self.widget
        if isinstance(w, ImageAttachWidget):
            return w.get_value()
        if isinstance(w, QComboBox):
            # Editable combos may hold user-entered text not in the list.
            if w.isEditable():
                return w.currentText().strip()
            data = w.currentData()
            return data if data is not None else w.currentText().strip()
        if isinstance(w, QLineEdit):
            return w.text().strip()
        return ""

    def set_value(self, value: str | None) -> None:
        text = value or ""
        w = self.widget
        if isinstance(w, ImageAttachWidget):
            w.set_value(text)
            return
        if isinstance(w, QComboBox):
            idx = w.findData(text)
            if idx < 0:
                idx = w.findText(text)
            if idx >= 0:
                w.setCurrentIndex(idx)
            elif w.isEditable():
                # Preserve unknown values (e.g. an odd lab code we haven't seen).
                w.setEditText(text)
            else:
                w.setCurrentIndex(0)
        elif isinstance(w, QLineEdit):
            w.setText(text)


def _make_widget(field: Field, parent: QWidget, growth_stages: list[tuple[str, str]]) -> QWidget:
    if field.kind == FieldKind.GROWTH_STAGE:
        cb = QComboBox(parent)
        cb.addItem("", "")
        for code, desc in growth_stages:
            label = f"{code} - {desc}"
            cb.addItem(label, label)
        return cb
    if field.kind in (FieldKind.DISEASE_PRESENCE, FieldKind.SEVERITY):
        cb = QComboBox(parent)
        for choice in field.choices:
            cb.addItem(choice, choice)
        return cb
    if field.kind == FieldKind.RATING:
        cb = QComboBox(parent)
        cb.setEditable(True)  # accept one-off lab codes outside the standard set
        for choice in field.choices:
            cb.addItem(choice, choice)
        return cb
    if field.kind == FieldKind.NUMBER:
        le = QLineEdit(parent)
        le.setValidator(QDoubleValidator(parent))
        return le
    if field.kind == FieldKind.IMAGES:
        return ImageAttachWidget(parent)
    # DATETIME / TEXT default
    le = QLineEdit(parent)
    if field.kind == FieldKind.DATETIME:
        le.setPlaceholderText("YYYY-MM-DD HH:MM")
    return le


# ---- Tab -------------------------------------------------------------------

class ObservationsTab(QWidget):
    def __init__(self, main_window) -> None:
        super().__init__(main_window)
        self._main = main_window
        self._bindings: dict[str, FieldBinding] = {}
        self._current_crop: str | None = None  # what we last built the form for
        self._growth_stages: list[tuple[str, str]] = []

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        outer.addLayout(self._build_location_bar())

        # Two-page form: 'Field observations' (what the surveyor enters) +
        # 'Lab report' (what the lab returns). Each page is its own scroll area.
        self.form_tabs = QTabWidget(self)
        self.field_host, self.field_host_layout = self._make_scroll_page()
        self.lab_host, self.lab_host_layout = self._make_scroll_page()
        self.form_tabs.addTab(self._wrap_scroll(self.field_host), "Field observations")
        self.form_tabs.addTab(self._wrap_scroll(self.lab_host), "Lab report")
        outer.addWidget(self.form_tabs, 1)

        # Bottom action bar
        outer.addLayout(self._build_action_bar())

        main_window.context_changed.connect(self._on_context_changed)

    # ---- scrollable page helpers ----------------------------------------

    @staticmethod
    def _make_scroll_page() -> tuple[QWidget, QVBoxLayout]:
        host = QWidget()
        layout = QVBoxLayout(host)
        layout.setContentsMargins(8, 8, 8, 8)
        return host, layout

    @staticmethod
    def _wrap_scroll(host: QWidget) -> QScrollArea:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(host)
        return scroll

    # ---- top: location selector ------------------------------------------

    def _build_location_bar(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setContentsMargins(8, 8, 8, 0)
        row.addWidget(QLabel("Location:"))
        self.location_combo = QComboBox(self)
        self.location_combo.setMinimumWidth(220)
        self.location_combo.currentIndexChanged.connect(self._on_location_changed)
        row.addWidget(self.location_combo)
        self.location_label = QLabel(self)
        self.location_label.setStyleSheet("color: gray;")
        row.addWidget(self.location_label)
        row.addStretch(1)
        return row

    # ---- bottom: actions --------------------------------------------------

    def _build_action_bar(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setContentsMargins(8, 0, 8, 8)
        self.status_label = QLabel("", self)
        self.status_label.setStyleSheet("color: #555;")
        row.addWidget(self.status_label, 1)

        self.reload_btn = QPushButton("Reload", self)
        self.reload_btn.clicked.connect(self._reload_record)
        row.addWidget(self.reload_btn)

        self.save_btn = QPushButton("Save", self)
        self.save_btn.setDefault(True)
        self.save_btn.clicked.connect(self._save_record)
        row.addWidget(self.save_btn)
        return row

    # ---- context handling -------------------------------------------------

    def _on_context_changed(self) -> None:
        crop = self._main.current_crop_code()
        week = self._main.current_iso_week()
        # Rebuild form if crop changed.
        if crop and crop != self._current_crop:
            self._rebuild_form(crop)
            self._populate_locations(crop)
        self._set_inputs_enabled(bool(crop and week))
        self._reload_record()
        if not week:
            self.status_label.setText("Pick or create a week to start entering observations.")
        elif not crop:
            self.status_label.setText("Pick a crop.")
        else:
            self.status_label.setText("")

    def _populate_locations(self, crop_code: str) -> None:
        self.location_combo.blockSignals(True)
        self.location_combo.clear()
        with connect() as conn:
            locs = list_locations(conn, crop_code)
        for loc in locs:
            self.location_combo.addItem(loc["location_id"], loc["location_id"])
        self.location_combo.blockSignals(False)
        self._update_location_label()

    def _update_location_label(self) -> None:
        crop = self._main.current_crop_code()
        loc_id = self.location_combo.currentData()
        if not crop or not loc_id:
            self.location_label.setText("")
            return
        with connect() as conn:
            for row in list_locations(conn, crop):
                if row["location_id"] == loc_id:
                    self.location_label.setText(f"({row['lat']}, {row['lon']})")
                    return
        self.location_label.setText("")

    def _on_location_changed(self) -> None:
        self._update_location_label()
        self._reload_record()

    def _set_inputs_enabled(self, enabled: bool) -> None:
        self.location_combo.setEnabled(enabled)
        self.save_btn.setEnabled(enabled)
        self.reload_btn.setEnabled(enabled)
        self.form_tabs.setEnabled(enabled)

    # ---- form construction -------------------------------------------------

    @staticmethod
    def _clear_layout(layout: QVBoxLayout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

    def _clear_form(self) -> None:
        self._clear_layout(self.field_host_layout)
        self._clear_layout(self.lab_host_layout)
        self._bindings.clear()

    def _rebuild_form(self, crop_code: str) -> None:
        self._clear_form()
        self._current_crop = crop_code

        # The form *structure* comes from the shared service so the desktop and
        # web frontends render the identical screen. This tab only turns that
        # structure into widgets.
        schema = obs_service.build_form_schema(crop_code)
        self._growth_stages = schema.growth_stages

        for section in schema.sections:
            host = self.field_host if section.page == "field" else self.lab_host
            layout = self.field_host_layout if section.page == "field" else self.lab_host_layout
            box = self._build_section(section, host)
            layout.addWidget(box)

        self.field_host_layout.addStretch(1)
        self.lab_host_layout.addStretch(1)

    def _build_section(self, section, host: QWidget) -> QGroupBox:
        box = QGroupBox(section.title, host)
        gs = self._growth_stages

        if section.kind == "tdr_grid":
            grid = QGridLayout(box)
            grid.addWidget(QLabel("<b>Sensor</b>", box), 0, 0)
            grid.addWidget(QLabel("<b>Temperature</b>", box), 0, 1)
            grid.addWidget(QLabel("<b>EC</b>", box), 0, 2)
            grid.addWidget(QLabel("<b>Moisture</b>", box), 0, 3)
            for r, tdr in enumerate(section.tdr_rows, start=1):
                grid.addWidget(QLabel(tdr.sensor_label, box), r, 0)
                for c, f in enumerate((tdr.temperature, tdr.ec, tdr.moisture), start=1):
                    if f is not None:
                        w = _make_widget(f, box, gs)
                        self._bindings[f.name] = FieldBinding(f, w)
                        grid.addWidget(w, r, c)
            return box

        if section.kind == "disease_table":
            grid = QGridLayout(box)
            grid.addWidget(QLabel("<b>Disease</b>", box), 0, 0)
            grid.addWidget(QLabel("<b>Presence</b>", box), 0, 1)
            grid.addWidget(QLabel("<b>Severity</b>", box), 0, 2)
            for i, row in enumerate(section.disease_rows, start=1):
                grid.addWidget(QLabel(row.label, box), i, 0)
                pw = _make_widget(row.presence, box, gs)
                self._bindings[row.presence.name] = FieldBinding(row.presence, pw)
                grid.addWidget(pw, i, 1)
                if row.severity:
                    sw = _make_widget(row.severity, box, gs)
                    self._bindings[row.severity.name] = FieldBinding(row.severity, sw)
                    grid.addWidget(sw, i, 2)
            grid.setColumnStretch(0, 2)
            grid.setColumnStretch(1, 1)
            grid.setColumnStretch(2, 1)
            return box

        if section.kind == "nutrient_table":
            grid = QGridLayout(box)
            grid.addWidget(QLabel("<b>Nutrient</b>", box), 0, 0)
            grid.addWidget(QLabel("<b>Value</b>", box), 0, 1)
            grid.addWidget(QLabel("<b>Rate</b>", box), 0, 2)
            for i, row in enumerate(section.nutrient_rows, start=1):
                grid.addWidget(QLabel(row.value.name, box), i, 0)
                vw = _make_widget(row.value, box, gs)
                self._bindings[row.value.name] = FieldBinding(row.value, vw)
                grid.addWidget(vw, i, 1)
                if row.rate:
                    rw = _make_widget(row.rate, box, gs)
                    self._bindings[row.rate.name] = FieldBinding(row.rate, rw)
                    grid.addWidget(rw, i, 2)
            grid.setColumnStretch(0, 1)
            grid.setColumnStretch(1, 1)
            grid.setColumnStretch(2, 1)
            return box

        if section.kind == "ratio_table":
            grid = QGridLayout(box)
            grid.addWidget(QLabel("<b>Ratio</b>", box), 0, 0)
            grid.addWidget(QLabel("<b>Actual</b>", box), 0, 1)
            grid.addWidget(QLabel("<b>Expected</b>", box), 0, 2)
            for i, row in enumerate(section.ratio_rows, start=1):
                grid.addWidget(QLabel(row.name, box), i, 0)
                aw = _make_widget(row.actual, box, gs)
                self._bindings[row.actual.name] = FieldBinding(row.actual, aw)
                grid.addWidget(aw, i, 1)
                if row.expected:
                    ew = _make_widget(row.expected, box, gs)
                    self._bindings[row.expected.name] = FieldBinding(row.expected, ew)
                    grid.addWidget(ew, i, 2)
            grid.setColumnStretch(0, 1)
            grid.setColumnStretch(1, 1)
            grid.setColumnStretch(2, 1)
            return box

        if section.kind == "images":
            v = QVBoxLayout(box)
            for f in section.fields:
                w = _make_widget(f, box, gs)
                self._bindings[f.name] = FieldBinding(f, w)
                v.addWidget(w)
            return box

        # Default: "form" — a label/widget per field.
        form = QFormLayout(box)
        for f in section.fields:
            w = _make_widget(f, box, gs)
            self._bindings[f.name] = FieldBinding(f, w)
            form.addRow(self._label_for(f), w)
        return box

    @staticmethod
    def _label_for(field: Field) -> str:
        return field.name.replace("_", " ")

    @staticmethod
    def _disease_display(name: str) -> str:
        # Strip the "Disease_" prefix for the table label.
        return name.removeprefix("Disease_").replace("_", " ")

    # ---- load / save ------------------------------------------------------

    def _reload_record(self) -> None:
        crop = self._main.current_crop_code()
        week = self._main.current_iso_week()
        loc = self.location_combo.currentData()
        # Image widget always needs to know the context, even when blank.
        if "Images" in self._bindings:
            img_widget = self._bindings["Images"].widget
            if isinstance(img_widget, ImageAttachWidget):
                img_widget.set_context(crop, week, loc)
        if not (crop and week and loc):
            for b in self._bindings.values():
                b.set_value("")
            return
        row = obs_service.load(crop, week, loc)
        for name, binding in self._bindings.items():
            binding.set_value(row.get(name, ""))
        if row:
            self.status_label.setText(f"Loaded {crop} / {week} / {loc}.")
        else:
            self.status_label.setText(f"New record for {crop} / {week} / {loc}.")

    def _save_record(self) -> None:
        crop = self._main.current_crop_code()
        week = self._main.current_iso_week()
        loc = self.location_combo.currentData()
        if not (crop and week and loc):
            QMessageBox.information(self, "Save", "Pick a crop, week, and location first.")
            return
        values = {name: binding.get_value() for name, binding in self._bindings.items()}
        try:
            obs_service.save(crop, week, loc, values)
        except Exception as exc:
            QMessageBox.critical(self, "Save failed", str(exc))
            return
        self.status_label.setText(f"Saved {crop} / {week} / {loc}.")
