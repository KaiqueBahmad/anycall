from PySide6.QtWidgets import QFrame, QHBoxLayout, QVBoxLayout, QLabel
from PySide6.QtCore import Signal

from app.models import Supplier
from app.theme import BG_SURFACE, BORDER, TEXT, TEXT_MUTED, ACCENT_ON, ACCENT_OFF
from .toggle import ToggleSwitch


class SupplierCard(QFrame):
    toggled = Signal(str, bool)

    def __init__(self, supplier: Supplier, parent=None):
        super().__init__(parent)
        self.supplier = supplier
        self._setup()

    def _setup(self):
        self.setObjectName("supplierCard")
        self._apply_style()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(6)

        # Row 1: status + name + toggle
        row1 = QHBoxLayout()
        row1.setContentsMargins(0, 0, 0, 0)
        row1.setSpacing(8)
        self._dot = QLabel("●")
        self._dot.setFixedWidth(8)
        self._dot.setStyleSheet(f"font-size: 6px;")
        name_lbl = QLabel(self.supplier.name)
        name_lbl.setStyleSheet(f"color: {TEXT}; font-weight: 500;")

        self._toggle = ToggleSwitch()
        self._toggle.setChecked(self.supplier.active)
        self._toggle.toggled.connect(self._on_toggle)

        row1.addWidget(self._dot)
        row1.addWidget(name_lbl)
        row1.addStretch()
        row1.addWidget(self._toggle)

        # Row 2: group
        row2 = QHBoxLayout()
        row2.setContentsMargins(0, 0, 0, 0)
        row2.setSpacing(8)
        group_lbl = QLabel(self.supplier.group)
        group_lbl.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 11px;")

        row2.addWidget(group_lbl)
        row2.addStretch()

        layout.addLayout(row1)
        layout.addLayout(row2)
        self._refresh_dot()

    def _on_toggle(self, checked: bool):
        self.supplier.active = checked
        self._refresh_dot()
        self._apply_style()
        self.toggled.emit(self.supplier.id, checked)

    def _refresh_dot(self):
        color = ACCENT_ON if self.supplier.active else TEXT_MUTED
        self._dot.setStyleSheet(f"color: {color}; font-size: 6px;")

    def _apply_style(self):
        if self.supplier.active:
            border = f"1px solid {ACCENT_ON}"
            bg = BG_SURFACE
        else:
            border = f"1px solid {BORDER}"
            bg = f"{BORDER}08"
        self.setStyleSheet(f"""
            #supplierCard {{
                background-color: {bg};
                border: {border};
            }}
        """)
