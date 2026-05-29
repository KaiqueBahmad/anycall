from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTextEdit, QFrame
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

        # Title container with margins
        title_container = QWidget()
        title_layout = QVBoxLayout(title_container)
        title_layout.setContentsMargins(16, 12, 16, 0)
        title_layout.setSpacing(0)
        title = QLabel("EXECUTION LOG")
        title.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 11px; font-weight: 600; letter-spacing: 1px;")
        title_layout.addWidget(title)
        layout.addWidget(title_container)

        # Meta bar container with margins
        meta_container = QWidget()
        meta_container.hide()
        meta_layout = QVBoxLayout(meta_container)
        meta_layout.setContentsMargins(16, 8, 16, 0)
        meta_layout.setSpacing(0)

        # Meta bar (column headers + data)
        self._meta_bar = QWidget()
        ml = QVBoxLayout(self._meta_bar)
        ml.setContentsMargins(0, 0, 0, 0)
        ml.setSpacing(0)

        # Column headers
        headers = QHBoxLayout()
        headers.setContentsMargins(0, 0, 0, 0)
        headers.setSpacing(48)
        for col_name in ["CONSUMER", "SUPPLIER", "DURATION", "STATUS"]:
            lbl = QLabel(col_name)
            lbl.setStyleSheet(f"color: {TEXT_SUBTLE}; font-size: 11px; font-weight: 600; letter-spacing: 0.5px;")
            headers.addWidget(lbl)
        headers.addStretch()
        ml.addLayout(headers)

        # Data row
        data_row = QHBoxLayout()
        data_row.setContentsMargins(0, 8, 0, 8)
        data_row.setSpacing(48)
        self._v_consumer = QLabel("—")
        self._v_consumer.setStyleSheet(f"color: {TEXT}; font-size: 13px; font-weight: 500;")
        self._v_supplier = QLabel("—")
        self._v_supplier.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 12px;")
        self._v_duration = QLabel("—")
        self._v_duration.setStyleSheet(f"color: {TEXT}; font-size: 11px; font-family: 'SF Mono', 'Courier', monospace;")
        self._v_status = QLabel("—")
        self._v_status.setStyleSheet(f"color: {TEXT}; font-size: 11px; font-weight: 500;")

        data_row.addWidget(self._v_consumer)
        data_row.addWidget(self._v_supplier)
        data_row.addWidget(self._v_duration)
        data_row.addWidget(self._v_status)
        data_row.addStretch()
        ml.addLayout(data_row)

        # Separator below table
        sep_table = QFrame()
        sep_table.setFixedHeight(1)
        sep_table.setStyleSheet(f"background: {BORDER};")
        ml.addWidget(sep_table)

        meta_layout.addWidget(self._meta_bar)
        meta_container.setLayout(meta_layout)
        self._meta_bar_container = meta_container

        # Placeholder
        self._placeholder = QLabel("Execute a consumer to see logs here")
        self._placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
        self._placeholder.setStyleSheet(f"color: {TEXT_SUBTLE}; font-size: 13px;")

        # Log text with margins
        log_container = QWidget()
        log_layout = QVBoxLayout(log_container)
        log_layout.setContentsMargins(16, 12, 16, 0)
        log_layout.setSpacing(0)
        self._log = QTextEdit()
        self._log.setReadOnly(True)
        self._log.hide()
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
        layout.addWidget(sep_table)
        layout.addWidget(self._placeholder)
        layout.addWidget(log_container, stretch=1)

    def show_result(self, result: ExecutionResult):
        duration_color = WARNING if result.duration_ms > 50 else SUCCESS
        status_color   = SUCCESS if result.success else ERROR

        self._v_consumer.setText(result.consumer.name)
        self._v_supplier.setText(result.supplier.name)

        self._v_duration.setText(f"{result.duration_ms}ms")
        self._v_duration.setStyleSheet(
            f"color: {duration_color}; font-size: 11px; font-family: 'SF Mono', 'Courier', monospace;"
        )

        self._v_status.setText("OK" if result.success else "ERROR")
        self._v_status.setStyleSheet(f"color: {status_color}; font-size: 11px; font-weight: 500;")

        self._placeholder.hide()
        self._meta_bar_container.show()
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
