from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTextEdit, QFrame
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QTextCursor

from app.models import ExecutionResult
from app.theme import (
    BG_PANEL, BG_SURFACE, BORDER,
    TEXT, TEXT_MUTED, TEXT_SUBTLE,
    SUCCESS, WARNING, ERROR, ACCENT_ON,
)

MONO = '"SF Mono", "Monaco", "Consolas", monospace'


class LogPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup()

    def _setup(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Header
        header = QFrame()
        header.setFixedHeight(40)
        header.setStyleSheet(f"background: {BG_SURFACE}; border-bottom: 1px solid {BORDER};")
        hl = QHBoxLayout(header)
        hl.setContentsMargins(16, 0, 16, 0)
        title = QLabel("EXECUTION LOG")
        title.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 10px; font-weight: 600; letter-spacing: 0.5px;")
        hl.addWidget(title)
        hl.addStretch()

        # Meta bar
        self._meta_bar = QFrame()
        self._meta_bar.hide()
        self._meta_bar.setFixedHeight(56)
        self._meta_bar.setStyleSheet(f"background: {BG_PANEL}; border-bottom: 1px solid {BORDER};")
        ml = QHBoxLayout(self._meta_bar)
        ml.setContentsMargins(16, 8, 16, 8)
        ml.setSpacing(32)

        self._v_consumer = self._make_chip("CONSUMER", ml)
        self._v_supplier = self._make_chip("SUPPLIER", ml)
        self._v_duration = self._make_chip("DURATION", ml)
        self._v_status   = self._make_chip("STATUS", ml)
        ml.addStretch()

        # Placeholder
        self._placeholder = QLabel("Execute a consumer to see logs here")
        self._placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
        self._placeholder.setStyleSheet(f"color: {TEXT_SUBTLE}; font-size: 13px;")

        # Log text
        self._log = QTextEdit()
        self._log.setReadOnly(True)
        self._log.hide()
        self._log.setStyleSheet(f"""
            QTextEdit {{
                background: {BG_PANEL};
                color: {TEXT};
                border: none;
                font-family: {MONO};
                font-size: 11px;
                padding: 16px 16px;
            }}
        """)

        layout.addWidget(header)
        layout.addWidget(self._meta_bar)
        layout.addWidget(self._placeholder)
        layout.addWidget(self._log)

    def _make_chip(self, label: str, parent_layout) -> QLabel:
        col = QWidget()
        cl = QVBoxLayout(col)
        cl.setContentsMargins(0, 4, 0, 4)
        cl.setSpacing(2)
        lbl = QLabel(label)
        lbl.setStyleSheet(f"color: {TEXT_SUBTLE}; font-size: 9px; font-weight: 600;")
        val = QLabel("—")
        val.setStyleSheet(f"color: {TEXT}; font-size: 11px; font-weight: 500;")
        cl.addWidget(lbl)
        cl.addWidget(val)
        parent_layout.addWidget(col)
        return val

    def show_result(self, result: ExecutionResult):
        duration_color = WARNING if result.duration_ms > 50 else SUCCESS
        status_color   = SUCCESS if result.success else ERROR

        self._v_consumer.setText(result.consumer.name)
        self._v_supplier.setText(result.supplier.name)

        self._v_duration.setText(f"{result.duration_ms}ms")
        self._v_duration.setStyleSheet(
            f"color: {duration_color}; font-size: 11px; font-weight: 500;"
        )

        self._v_status.setText("OK" if result.success else "ERROR")
        self._v_status.setStyleSheet(f"color: {status_color}; font-size: 11px; font-weight: 600;")

        self._placeholder.hide()
        self._meta_bar.show()
        self._log.show()

        self._log.clear()
        html_lines = []
        for line in result.lines:
            esc = line.replace("&", "&amp;").replace("<", "&lt;")
            if "[REQUEST]" in line or "XADD" in line:
                color = ACCENT_ON
            elif "[RESPONSE]" in line or "received" in line.lower():
                color = SUCCESS
            elif "[SERVER]" in line:
                color = ACCENT_ON
            elif "[CLIENT]" in line:
                color = TEXT_MUTED
            elif "ERROR" in line:
                color = ERROR
            elif line.startswith("#"):
                color = TEXT_SUBTLE
            elif not line.strip():
                color = TEXT_SUBTLE
            else:
                color = TEXT_MUTED
            html_lines.append(f'<span style="color:{color};">{esc}</span>')

        self._log.setHtml(
            '<div style="line-height:1.6; white-space:pre;">'
            + "<br>".join(html_lines)
            + "</div>"
        )
        cursor = self._log.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self._log.setTextCursor(cursor)
