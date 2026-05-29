from PySide6.QtWidgets import QFrame, QHBoxLayout, QVBoxLayout, QLabel, QPushButton
from PySide6.QtCore import Signal, Qt

from app.models import Consumer
from app.theme import BG_SURFACE, BORDER, TEXT, TEXT_MUTED, ACCENT_ON, LANG_COLORS


class ConsumerCard(QFrame):
    run_requested = Signal(str)

    def __init__(self, consumer: Consumer, parent=None):
        super().__init__(parent)
        self.consumer = consumer
        self._setup()

    def _setup(self):
        self.setObjectName("consumerCard")
        self.setStyleSheet(f"""
            #consumerCard {{
                background-color: {BG_SURFACE};
                border: 1px solid {BORDER};
            }}
        """)
        self.setFixedHeight(56)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(10)

        # Language badge — full name
        accent = LANG_COLORS.get(self.consumer.language, TEXT_MUTED)
        lang_name = {"java": "Java", "python": "Python", "go": "Go"}.get(
            self.consumer.language, self.consumer.language.upper()
        )
        badge = QLabel(lang_name)
        badge.setFixedSize(60, 24)
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.setStyleSheet(f"""
            background-color: {accent}20;
            color: {accent};
            border: 1px solid {accent}60;
            font-size: 10px;
            font-weight: 600;
        """)

        # Run button
        self._run_btn = QPushButton("▶")
        self._run_btn.setFixedSize(36, 36)
        self._run_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._run_btn.setStyleSheet(f"""
            QPushButton {{
                background: {ACCENT_ON}15;
                color: {ACCENT_ON};
                border: 1px solid {ACCENT_ON}60;
                font-size: 12px;
                font-weight: 600;
                padding: 0px;
            }}
            QPushButton:hover {{
                background: {ACCENT_ON}25;
            }}
            QPushButton:disabled {{
                background: {BORDER};
                color: {TEXT_MUTED};
                border-color: {BORDER};
            }}
        """)
        self._run_btn.clicked.connect(lambda: self.run_requested.emit(self.consumer.id))

        layout.addWidget(badge)
        layout.addStretch()
        layout.addWidget(self._run_btn)
