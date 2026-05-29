import datetime
import random

from PySide6.QtWidgets import QFrame, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTextEdit
from PySide6.QtCore import Signal, QPropertyAnimation, QEasingCurve, QPoint, Qt

from app.models import Supplier
from app.theme import BG_PANEL, BG_SURFACE, BORDER, TEXT, TEXT_MUTED, TEXT_SUBTLE, ACCENT_ON

MONO = '"SF Mono", "Monaco", "Consolas", monospace'


class SupplierDrawer(QFrame):
    closed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._supplier: Supplier | None = None
        self._setup()

        self._anim = QPropertyAnimation(self, b"pos", self)
        self._anim.setDuration(250)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)

    def _setup(self):
        self.setObjectName("drawer")
        self.setStyleSheet(f"""
            #drawer {{
                background-color: {BG_PANEL};
                border-right: 1px solid {BORDER};
            }}
        """)
        self.hide()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Header
        header = QFrame()
        header.setFixedHeight(48)
        header.setStyleSheet(f"background: {BG_SURFACE}; border-bottom: 1px solid {BORDER};")
        hl = QHBoxLayout(header)
        hl.setContentsMargins(16, 0, 16, 0)

        self._dot = QLabel("●")
        self._dot.setFixedWidth(8)
        self._dot.setStyleSheet("font-size: 6px;")

        self._title = QLabel()
        self._title.setStyleSheet(f"color: {TEXT}; font-weight: 500;")

        close_btn = QPushButton("✕")
        close_btn.setFixedSize(28, 28)
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                color: {TEXT_MUTED};
                border: none;
                font-size: 14px;
            }}
            QPushButton:hover {{
                background: {BORDER};
                color: {TEXT};
            }}
        """)
        close_btn.clicked.connect(self._close)

        hl.addWidget(self._dot)
        hl.addWidget(self._title)
        hl.addStretch()
        hl.addWidget(close_btn)

        # Log
        self._log = QTextEdit()
        self._log.setReadOnly(True)
        self._log.setStyleSheet(f"""
            QTextEdit {{
                background: {BG_PANEL};
                color: {TEXT};
                border: none;
                font-family: {MONO};
                font-size: 10px;
                padding: 12px 16px;
            }}
        """)

        layout.addWidget(header)
        layout.addWidget(self._log)

    def open_for(self, supplier: Supplier, width: int, height: int):
        self._supplier = supplier
        self.resize(width, height)
        self.move(-width, 0)
        self.show()
        self.raise_()

        dot_color = ACCENT_ON if supplier.active else TEXT_MUTED
        self._dot.setStyleSheet(f"color: {dot_color}; font-size: 6px;")
        self._title.setText(supplier.name)

        self._populate_logs(supplier)

        self._anim.stop()
        try:
            self._anim.finished.disconnect()
        except RuntimeError:
            pass
        self._anim.setStartValue(QPoint(-width, 0))
        self._anim.setEndValue(QPoint(0, 0))
        self._anim.start()

    def _close(self):
        self._anim.stop()
        try:
            self._anim.finished.disconnect()
        except RuntimeError:
            pass
        self._anim.setDuration(200)
        self._anim.setEasingCurve(QEasingCurve.Type.InCubic)
        self._anim.setStartValue(self.pos())
        self._anim.setEndValue(QPoint(-self.width(), 0))
        self._anim.finished.connect(self._on_close_done)
        self._anim.start()

    def _on_close_done(self):
        self.hide()
        self._anim.setDuration(250)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.closed.emit()

    def _populate_logs(self, supplier: Supplier):
        self._log.clear()

        base = datetime.datetime.now()
        lines: list[tuple[str, str]] = [
            (TEXT_SUBTLE, f"# {supplier.name}  ·  {supplier.group}"),
            (TEXT_SUBTLE, ""),
        ]

        if not supplier.active:
            lines.append((TEXT_MUTED, f"[OFF] Supplier is offline"))
            self._render(lines)
            return

        events = [
            (TEXT_MUTED, f"[INFO] Consumer group '{supplier.group}' created"),
            (TEXT_MUTED, f"[INFO] Listening on stream..."),
            (ACCENT_ON, f"[XREADGROUP] requestId=a3f1c2 · method=createProduct"),
            (ACCENT_ON, f"[DESERIALIZE] Payload processed in {random.randint(1,4)}ms"),
            (TEXT_MUTED, f"[INVOKE] createProduct() executed in {random.randint(3,15)}ms"),
            (TEXT_MUTED, f"[RESPONSE] XADD ·  {random.randint(0,2)}ms"),
            (TEXT_MUTED, f"[INFO] Ready for next message"),
        ]

        for i, (color, msg) in enumerate(events):
            delta = len(events) - i - 1
            ts = (base - datetime.timedelta(seconds=delta)).strftime("%H:%M:%S")
            lines.append((color, f"[{ts}] {msg}"))

        self._render(lines)

    def _render(self, lines: list[tuple[str, str]]):
        html = []
        for color, line in lines:
            esc = line.replace("&", "&amp;").replace("<", "&lt;")
            html.append(f'<span style="color:{color};">{esc}</span>')
        self._log.setHtml(
            '<div style="line-height:1.6; white-space:pre;">'
            + "<br>".join(html)
            + "</div>"
        )
