from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTextEdit, QFrame, QPushButton
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QTextCursor

from app.models import ExecutionResult
from app.theme import (
    BORDER,
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

        # Title container
        title_container = QWidget()
        title_layout = QHBoxLayout(title_container)
        title_layout.setContentsMargins(16, 12, 16, 0)
        title_layout.setSpacing(12)

        title = QLabel("EXECUTION LOG")
        title.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 11px; font-weight: 600; letter-spacing: 1px;")
        title_layout.addWidget(title)
        title_layout.addStretch()

        clear_btn = QPushButton("clear")
        clear_btn.setFixedSize(42, 18)
        clear_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        clear_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                color: {TEXT_SUBTLE};
                border: 1px solid rgba(255,255,255,0.08);
                border-radius: 3px;
                font-size: 10px;
            }}
            QPushButton:hover {{
                border-color: rgba(255,255,255,0.2);
                color: {TEXT_MUTED};
            }}
            QPushButton:pressed {{
                background: rgba(255,255,255,0.05);
            }}
        """)
        clear_btn.clicked.connect(self._on_clear)
        title_layout.addWidget(clear_btn)

        layout.addWidget(title_container)

        # Meta bar container
        meta_container = QWidget()
        meta_layout = QVBoxLayout(meta_container)
        meta_layout.setContentsMargins(16, 8, 16, 0)
        meta_layout.setSpacing(0)

        self._meta_bar = QWidget()
        ml = QVBoxLayout(self._meta_bar)
        ml.setContentsMargins(0, 0, 0, 0)
        ml.setSpacing(0)

        # Column headers
        headers = QHBoxLayout()
        headers.setContentsMargins(0, 0, 0, 0)
        headers.setSpacing(16)

        for label, width in [("CONSUMER", 120), ("SUPPLIER", 120), ("DURATION", 100), ("STATUS", 80)]:
            h = QLabel(label)
            h.setMinimumWidth(width)
            h.setStyleSheet(f"color: {TEXT_SUBTLE}; font-size: 11px; font-weight: 600; letter-spacing: 0.5px;")
            headers.addWidget(h)

        headers.addStretch()
        ml.addLayout(headers)

        # Data row
        data_row = QHBoxLayout()
        data_row.setContentsMargins(0, 8, 0, 8)
        data_row.setSpacing(16)

        self._v_consumer = QLabel("—")
        self._v_consumer.setMinimumWidth(120)
        self._v_consumer.setStyleSheet(f"color: {TEXT}; font-size: 13px; font-weight: 500;")

        self._v_supplier = QLabel("—")
        self._v_supplier.setMinimumWidth(120)
        self._v_supplier.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 12px;")

        self._v_duration = QLabel("—")
        self._v_duration.setMinimumWidth(100)
        self._v_duration.setStyleSheet(f"color: {TEXT}; font-size: 11px; font-family: 'SF Mono', 'Courier', monospace;")

        self._v_status = QLabel("—")
        self._v_status.setMinimumWidth(80)
        self._v_status.setStyleSheet(f"color: {TEXT}; font-size: 11px; font-weight: 500;")

        for w in [self._v_consumer, self._v_supplier, self._v_duration, self._v_status]:
            data_row.addWidget(w)
        data_row.addStretch()
        ml.addLayout(data_row)

        sep_table = QFrame()
        sep_table.setFixedHeight(1)
        sep_table.setStyleSheet(f"background: {BORDER};")
        ml.addWidget(sep_table)

        meta_layout.addWidget(self._meta_bar)
        meta_container.setLayout(meta_layout)
        self._meta_bar_container = meta_container

        # Log text
        log_container = QWidget()
        log_layout = QVBoxLayout(log_container)
        log_layout.setContentsMargins(16, 12, 16, 0)
        log_layout.setSpacing(0)

        self._log = QTextEdit()
        self._log.setReadOnly(True)
        self._log.setStyleSheet(f"""
            QTextEdit {{
                background: transparent;
                color: {TEXT};
                border: none;
                font-family: {MONO};
                font-size: 11px;
                padding: 0px;
            }}
        """)
        log_layout.addWidget(self._log)

        layout.addWidget(self._meta_bar_container)
        layout.addWidget(log_container, stretch=1)

    def _on_clear(self):
        self._log.clear()
        self._v_consumer.setText("—")
        self._v_supplier.setText("—")
        self._v_duration.setText("—")
        self._v_status.setText("—")

    def add_log_line(self, line: str, line_type: str = "info"):
        cursor = self._log.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)

        color_map = {
            "info": TEXT_MUTED,
            "success": SUCCESS,
            "error": ERROR,
            "warning": WARNING,
            "header": TEXT_SUBTLE,
        }
        color = color_map.get(line_type, TEXT_MUTED)

        esc = line.replace("&", "&amp;").replace("<", "&lt;")
        html = f'<span style="color:{color};">{esc}</span><br>'

        self._log.insertHtml(html)
        cursor = self._log.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self._log.setTextCursor(cursor)

    def show_result(self, result: ExecutionResult):
        duration_color = WARNING if result.duration_ms > 50 else SUCCESS
        status_color   = SUCCESS if result.success else ERROR

        self._v_consumer.setText(result.consumer.name if result.consumer else "—")
        self._v_supplier.setText(result.supplier.name if result.supplier else "—")

        if result.duration_ms > 0:
            self._v_duration.setText(f"{result.duration_ms}ms")
            self._v_duration.setStyleSheet(
                f"color: {duration_color}; font-size: 11px; font-family: 'SF Mono', 'Courier', monospace;"
            )
        else:
            self._v_duration.setText("—")

        self._v_status.setText("OK" if result.success else "ERROR")
        self._v_status.setStyleSheet(f"color: {status_color}; font-size: 11px; font-weight: 500;")

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
