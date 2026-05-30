from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton
from PySide6.QtCore import Signal, Qt

from app.theme import TEXT, TEXT_MUTED, ACCENT_ON, ACCENT_OFF
from app.services.state import ServiceStateManager, ServiceState


class ServiceStatusBar(QFrame):
    """Shows service status (Redis) with toggle button."""

    toggled = Signal(bool)

    def __init__(self, label: str, state_manager: ServiceStateManager, service_name: str, parent=None):
        super().__init__(parent)
        self.label = label
        self.service_name = service_name
        self.state_manager = state_manager
        self._is_running = False
        self._setup()
        self.state_manager.register_listener(self._on_state_changed)

    def _setup(self):
        self.setObjectName("serviceStatusBar")
        self.setFixedHeight(50)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 0, 16, 0)
        layout.setSpacing(12)

        # Status indicator (circle)
        self._dot = QLabel("●")
        self._dot.setFixedSize(8, 8)
        self._dot.setStyleSheet(f"color: {ACCENT_OFF}; font-size: 8px;")

        # Label
        lbl = QLabel(self.label)
        lbl.setStyleSheet(f"color: {TEXT}; font-weight: 500; font-size: 11px;")

        # Toggle button
        self._btn = QPushButton("Start")
        self._btn.setFixedSize(50, 24)
        self._btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn.clicked.connect(self._on_button_clicked)
        self._btn.setStyleSheet(f"""
            QPushButton {{
                background: {ACCENT_OFF}20;
                color: {TEXT};
                border: 1px solid {ACCENT_OFF};
                border-radius: 3px;
                font-size: 10px;
                font-weight: 500;
            }}
            QPushButton:hover {{
                background: {ACCENT_OFF}30;
                border-color: {ACCENT_OFF};
            }}
            QPushButton:pressed {{
                background: {ACCENT_OFF}40;
            }}
        """)

        layout.addWidget(self._dot)
        layout.addWidget(lbl)
        layout.addStretch()
        layout.addWidget(self._btn)

    def _on_button_clicked(self):
        self.toggled.emit(not self._is_running)

    def _on_state_changed(self):
        """Called when any service state changes."""
        state = self.state_manager.get_state(self.service_name)
        self._is_running = state == ServiceState.RUNNING

        # Update button
        is_loading = state in (ServiceState.STARTING, ServiceState.STOPPING)
        self._btn.setEnabled(not is_loading)

        if state == ServiceState.RUNNING:
            self._btn.setText("Stop")
            self._btn.setStyleSheet(f"""
                QPushButton {{
                    background: {ACCENT_ON}20;
                    color: {ACCENT_ON};
                    border: 1px solid {ACCENT_ON};
                    border-radius: 3px;
                    font-size: 10px;
                    font-weight: 500;
                }}
                QPushButton:hover {{
                    background: {ACCENT_ON}30;
                }}
                QPushButton:pressed {{
                    background: {ACCENT_ON}40;
                }}
            """)
        else:
            self._btn.setText("Start")
            self._btn.setStyleSheet(f"""
                QPushButton {{
                    background: {ACCENT_OFF}20;
                    color: {TEXT};
                    border: 1px solid {ACCENT_OFF};
                    border-radius: 3px;
                    font-size: 10px;
                    font-weight: 500;
                }}
                QPushButton:hover {{
                    background: {ACCENT_OFF}30;
                }}
                QPushButton:pressed {{
                    background: {ACCENT_OFF}40;
                }}
            """)

        # Update indicator dot
        if state == ServiceState.RUNNING:
            self._dot.setStyleSheet(f"color: {ACCENT_ON}; font-size: 8px;")
        elif state in (ServiceState.STARTING, ServiceState.STOPPING):
            self._dot.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 8px;")
        else:
            self._dot.setStyleSheet(f"color: {ACCENT_OFF}; font-size: 8px;")
