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

from app.crops import crop_by_code
from app.db import (
    connect,
    list_growth_stages,
    list_locations,
    load_obs_row,
    save_obs_row,
)
from app.schema import (
    Field,
    FieldKind,
    pair_disease_fields,
    pair_nutrient_fields,
    pair_ratio_fields,
    petal_test_fields,
    read_template_fields,
    tdr_fields,
)
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
        crop = crop_by_code(crop_code)
        fields = read_template_fields(crop.template_path)
        by_name = {f.name: f for f in fields}

        with connect() as conn:
            growth_stages = [
                (r["code"], r["description"])
                for r in list_growth_stages(conn, crop_code)
            ]

        field_host = self.field_host
        lab_host = self.lab_host
        field_layout = self.field_host_layout
        lab_layout = self.lab_host_layout

        # ====================================================================
        # FIELD OBSERVATIONS PAGE
        # ====================================================================

        # --- Section: Header (Date_Time, Growth stage) ---------------------
        header_box = QGroupBox("Observation header", field_host)
        hf = QFormLayout(header_box)
        for name in ("Date_Time",):
            f = by_name.get(name)
            if f:
                w = _make_widget(f, header_box, growth_stages)
                self._bindings[name] = FieldBinding(f, w)
                hf.addRow(self._label_for(f), w)
        for f in fields:
            if f.kind == FieldKind.GROWTH_STAGE:
                w = _make_widget(f, header_box, growth_stages)
                self._bindings[f.name] = FieldBinding(f, w)
                hf.addRow(self._label_for(f), w)
        field_layout.addWidget(header_box)

        # --- Section: Soil (TDR sensors) -----------------------------------
        soil_box = QGroupBox("Soil readings (TDR)", field_host)
        soil_grid = QGridLayout(soil_box)
        soil_grid.addWidget(QLabel("<b>Sensor</b>", soil_box), 0, 0)
        soil_grid.addWidget(QLabel("<b>Temperature</b>", soil_box), 0, 1)
        soil_grid.addWidget(QLabel("<b>EC</b>", soil_box), 0, 2)
        soil_grid.addWidget(QLabel("<b>Moisture</b>", soil_box), 0, 3)
        for sensor_idx in (1, 2, 3):
            r = sensor_idx
            soil_grid.addWidget(QLabel(f"TDR {sensor_idx}", soil_box), r, 0)
            for c, suffix in enumerate(("TEMPERATURE", "EC", "MOISTURE"), start=1):
                fname = f"TDR_{sensor_idx}_SOIL_{suffix}"
                f = by_name.get(fname)
                if f:
                    w = _make_widget(f, soil_box, growth_stages)
                    self._bindings[fname] = FieldBinding(f, w)
                    soil_grid.addWidget(w, r, c)
        field_layout.addWidget(soil_box)

        # --- Section: Diseases ---------------------------------------------
        disease_box = QGroupBox("Diseases", field_host)
        d_grid = QGridLayout(disease_box)
        d_grid.addWidget(QLabel("<b>Disease</b>", disease_box), 0, 0)
        d_grid.addWidget(QLabel("<b>Presence</b>", disease_box), 0, 1)
        d_grid.addWidget(QLabel("<b>Severity</b>", disease_box), 0, 2)
        for i, (presence, severity) in enumerate(pair_disease_fields(fields), start=1):
            d_grid.addWidget(QLabel(self._disease_display(presence.name), disease_box), i, 0)
            pw = _make_widget(presence, disease_box, growth_stages)
            self._bindings[presence.name] = FieldBinding(presence, pw)
            d_grid.addWidget(pw, i, 1)
            if severity:
                sw = _make_widget(severity, disease_box, growth_stages)
                self._bindings[severity.name] = FieldBinding(severity, sw)
                d_grid.addWidget(sw, i, 2)
        d_grid.setColumnStretch(0, 2)
        d_grid.setColumnStretch(1, 1)
        d_grid.setColumnStretch(2, 1)
        field_layout.addWidget(disease_box)

        # --- Section: Insects ----------------------------------------------
        insect_box = QGroupBox("Insects", field_host)
        i_form = QFormLayout(insect_box)
        for name in ("Insect_Damage", "Insect_Identification"):
            f = by_name.get(name)
            if f:
                w = _make_widget(f, insect_box, growth_stages)
                self._bindings[name] = FieldBinding(f, w)
                i_form.addRow(self._label_for(f), w)
        field_layout.addWidget(insect_box)

        # --- Section: Petal test (canola only) -----------------------------
        petal = petal_test_fields(fields)
        if petal:
            petal_box = QGroupBox("Petal test", field_host)
            p_form = QFormLayout(petal_box)
            for f in petal:
                w = _make_widget(f, petal_box, growth_stages)
                self._bindings[f.name] = FieldBinding(f, w)
                p_form.addRow(self._label_for(f), w)
            field_layout.addWidget(petal_box)

        # --- Section: Images -----------------------------------------------
        if "Images" in by_name:
            f = by_name["Images"]
            images_box = QGroupBox("Photos", field_host)
            img_v = QVBoxLayout(images_box)
            widget = _make_widget(f, images_box, growth_stages)
            self._bindings["Images"] = FieldBinding(f, widget)
            img_v.addWidget(widget)
            field_layout.addWidget(images_box)

        field_layout.addStretch(1)

        # ====================================================================
        # LAB REPORT PAGE
        # ====================================================================

        # --- Section: Report identifiers -----------------------------------
        report_box = QGroupBox("Report identifiers", lab_host)
        report_form = QFormLayout(report_box)
        for name in ("ReportNo", "Lab_No.", "Disease_Report_Results"):
            f = by_name.get(name)
            if f:
                w = _make_widget(f, report_box, growth_stages)
                self._bindings[name] = FieldBinding(f, w)
                report_form.addRow(self._label_for(f), w)
        lab_layout.addWidget(report_box)

        # --- Section: Nutrient panel ---------------------------------------
        nut_box = QGroupBox("Nutrient panel", lab_host)
        nut_grid = QGridLayout(nut_box)
        nut_grid.addWidget(QLabel("<b>Nutrient</b>", nut_box), 0, 0)
        nut_grid.addWidget(QLabel("<b>Value</b>", nut_box), 0, 1)
        nut_grid.addWidget(QLabel("<b>Rate</b>", nut_box), 0, 2)
        for i, (val_f, rate_f) in enumerate(pair_nutrient_fields(fields), start=1):
            nut_grid.addWidget(QLabel(val_f.name, nut_box), i, 0)
            vw = _make_widget(val_f, nut_box, growth_stages)
            self._bindings[val_f.name] = FieldBinding(val_f, vw)
            nut_grid.addWidget(vw, i, 1)
            if rate_f:
                rw = _make_widget(rate_f, nut_box, growth_stages)
                self._bindings[rate_f.name] = FieldBinding(rate_f, rw)
                nut_grid.addWidget(rw, i, 2)
        nut_grid.setColumnStretch(0, 1)
        nut_grid.setColumnStretch(1, 1)
        nut_grid.setColumnStretch(2, 1)
        lab_layout.addWidget(nut_box)

        # --- Section: Nutrient ratios --------------------------------------
        ratio_box = QGroupBox("Nutrient ratios", lab_host)
        r_grid = QGridLayout(ratio_box)
        r_grid.addWidget(QLabel("<b>Ratio</b>", ratio_box), 0, 0)
        r_grid.addWidget(QLabel("<b>Actual</b>", ratio_box), 0, 1)
        r_grid.addWidget(QLabel("<b>Expected</b>", ratio_box), 0, 2)
        for i, (name, actual, expected) in enumerate(pair_ratio_fields(fields), start=1):
            r_grid.addWidget(QLabel(name, ratio_box), i, 0)
            aw = _make_widget(actual, ratio_box, growth_stages)
            self._bindings[actual.name] = FieldBinding(actual, aw)
            r_grid.addWidget(aw, i, 1)
            if expected:
                ew = _make_widget(expected, ratio_box, growth_stages)
                self._bindings[expected.name] = FieldBinding(expected, ew)
                r_grid.addWidget(ew, i, 2)
        r_grid.setColumnStretch(0, 1)
        r_grid.setColumnStretch(1, 1)
        r_grid.setColumnStretch(2, 1)
        lab_layout.addWidget(ratio_box)

        lab_layout.addStretch(1)

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
        with connect() as conn:
            row = load_obs_row(conn, crop, week, loc)
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
            with connect() as conn:
                save_obs_row(conn, crop, week, loc, values)
        except Exception as exc:
            QMessageBox.critical(self, "Save failed", str(exc))
            return
        self.status_label.setText(f"Saved {crop} / {week} / {loc}.")
