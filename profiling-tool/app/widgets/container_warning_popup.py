from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame,
)
from PySide6.QtCore import Qt, Signal


class ContainerWarningPopup(QWidget):
    confirmed = Signal()
    cancelled = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet("""
            QWidget {
                background-color: rgba(0, 0, 0, 150);
            }
        """)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Dialog box
        dialog = QFrame()
        dialog.setStyleSheet("""
            QFrame {
                background-color: #1e1e1e;
            }
        """)
        dialog.setMaximumWidth(400)
        dialog_layout = QVBoxLayout(dialog)
        dialog_layout.setContentsMargins(24, 24, 24, 24)
        dialog_layout.setSpacing(16)

        # Title
        title = QLabel("Running Containers Detected")
        title.setStyleSheet("""
            color: #ffffff;
            font-size: 16px;
            font-weight: 600;
        """)
        dialog_layout.addWidget(title)

        # Message
        message = QLabel("There are running containers in docker-compose.\n\nDo you want to stop them?")
        message.setStyleSheet("""
            color: #b0b0b0;
            font-size: 13px;
            line-height: 20px;
        """)
        message.setWordWrap(True)
        dialog_layout.addWidget(message)

        # Buttons
        buttons_layout = QHBoxLayout()
        buttons_layout.setSpacing(12)
        buttons_layout.addStretch()

        cancel_btn = QPushButton("No")
        cancel_btn.setStyleSheet("""
            QPushButton {
                background-color: #3a3a3a;
                color: #ffffff;
                border: none;
                padding: 8px 16px;
                font-size: 12px;
                font-weight: 500;
            }
            QPushButton:hover {
                background-color: #4a4a4a;
            }
            QPushButton:pressed {
                background-color: #2a2a2a;
            }
        """)
        cancel_btn.clicked.connect(self._on_cancel)
        buttons_layout.addWidget(cancel_btn)

        confirm_btn = QPushButton("Yes, Stop Them")
        confirm_btn.setStyleSheet("""
            QPushButton {
                background-color: #e74c3c;
                color: #ffffff;
                border: none;
                padding: 8px 16px;
                font-size: 12px;
                font-weight: 500;
            }
            QPushButton:hover {
                background-color: #c0392b;
            }
            QPushButton:pressed {
                background-color: #a93226;
            }
        """)
        confirm_btn.clicked.connect(self._on_confirm)
        buttons_layout.addWidget(confirm_btn)

        dialog_layout.addLayout(buttons_layout)

        layout.addWidget(dialog, alignment=Qt.AlignmentFlag.AlignCenter)

    def _on_confirm(self):
        self.confirmed.emit()
        self.hide()

    def _on_cancel(self):
        self.cancelled.emit()
        self.hide()

    def showEvent(self, event):
        super().showEvent(event)
        if self.parent():
            self.setGeometry(self.parent().rect())
