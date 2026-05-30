import os
import logging

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QLabel,
    QScrollArea, QFrame, QSplitter,
)
from PySide6.QtCore import Qt, QTimer

from app.models import Supplier, Consumer
from app.fixtures import MOCK_SUPPLIERS, MOCK_CONSUMERS
from app.theme import BG_PANEL, BORDER, TEXT_MUTED, PANEL_WIDTH
from app.widgets.supplier_card import SupplierCard
from app.widgets.consumer_card import ConsumerCard
from app.widgets.log_panel import LogPanel
from app.widgets.container_warning_popup import ConfirmationDialog
from app.widgets.service_status_bar import ServiceStatusBar
from app.services.state import ServiceStateManager, ServiceState
from app.services.service_manager import ServiceManager
from app.services.events import EventBus

logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("AnyCall Profiling Tool")
        self.resize(1100, 700)
        self.setMinimumSize(820, 520)

        self._root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

        self._events = EventBus()
        self._state_manager = ServiceStateManager()
        self._service_manager = ServiceManager(self._root_dir, self._state_manager, self._events)

        self._suppliers: dict[str, Supplier] = {s.id: s for s in MOCK_SUPPLIERS}
        self._consumers: dict[str, Consumer] = {c.id: c for c in MOCK_CONSUMERS}
        self._supplier_cards: dict[str, SupplierCard] = {}
        self._consumer_cards: dict[str, ConsumerCard] = {}

        self._build_ui()
        self._setup_listeners()
        QTimer.singleShot(500, self._check_running_containers)

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)

        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_left_panel(central))

        divider = QFrame()
        divider.setFixedWidth(1)
        divider.setStyleSheet(f"background: {BORDER};")
        root.addWidget(divider)

        root.addWidget(self._build_right_panel(central), stretch=1)

        self._popup = ConfirmationDialog(
            title="Running Containers Detected",
            message="There are running containers in docker-compose.\n\nDo you want to stop them?",
            confirm_text="Yes, Stop Them",
            cancel_text="No",
            parent=central,
        )
        self._popup.confirmed.connect(self._on_stop_all)
        self._popup.cancelled.connect(lambda: None)
        self._popup.hide()

    def _build_left_panel(self, parent: QWidget) -> QWidget:
        panel = QWidget(parent)
        panel.setFixedWidth(PANEL_WIDTH)
        panel.setStyleSheet(f"background: {BG_PANEL};")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(1)

        redis_widget = QWidget()
        redis_layout = QVBoxLayout(redis_widget)
        redis_layout.setContentsMargins(0, 0, 0, 0)
        redis_layout.setSpacing(0)

        self._redis_status = ServiceStatusBar("REDIS", self._events, "redis")
        self._redis_status.toggled.connect(self._service_manager.toggle_redis)
        redis_layout.addWidget(self._redis_status)

        redis_scroll = QScrollArea()
        redis_scroll.setWidgetResizable(True)
        redis_scroll.setFrameShape(QFrame.Shape.NoFrame)
        redis_scroll.setStyleSheet("background: transparent;")
        redis_scroll.setWidget(QWidget())
        redis_layout.addWidget(redis_scroll)

        suppliers_widget = QWidget()
        sl = QVBoxLayout(suppliers_widget)
        sl.setContentsMargins(0, 0, 0, 0)
        sl.setSpacing(0)
        sl.addWidget(self._section_header("SUPPLIERS"))

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("background: transparent;")

        container = QWidget()
        container.setStyleSheet("background: transparent;")
        vbox = QVBoxLayout(container)
        vbox.setContentsMargins(12, 12, 12, 12)
        vbox.setSpacing(8)

        for supplier in self._suppliers.values():
            card = SupplierCard(supplier)
            card.toggled.connect(lambda supplier_id, active, sid=supplier.id: self._on_supplier_toggled(sid, active))
            card.build_requested.connect(self._on_build_requested)
            self._supplier_cards[supplier.id] = card
            vbox.addWidget(card)

        vbox.addStretch()
        scroll.setWidget(container)
        sl.addWidget(scroll)

        consumers_widget = QWidget()
        cl = QVBoxLayout(consumers_widget)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(0)
        cl.addWidget(self._section_header("CONSUMERS"))

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        container = QWidget()
        vbox = QVBoxLayout(container)
        vbox.setContentsMargins(16, 12, 16, 12)
        vbox.setSpacing(8)

        for consumer in self._consumers.values():
            card = ConsumerCard(consumer)
            card.run_requested.connect(self._on_run_requested)
            self._consumer_cards[consumer.id] = card
            vbox.addWidget(card)

        vbox.addStretch()
        scroll.setWidget(container)
        cl.addWidget(scroll)

        splitter.addWidget(redis_widget)
        splitter.addWidget(suppliers_widget)
        splitter.addWidget(consumers_widget)
        splitter.setSizes([80, 220, 280])

        layout.addWidget(splitter)
        return panel

    def _build_right_panel(self, parent: QWidget) -> QWidget:
        panel = QWidget(parent)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._log_panel = LogPanel()
        layout.addWidget(self._log_panel)
        return panel

    def _section_header(self, title: str) -> QFrame:
        header = QFrame()
        header.setFixedHeight(40)
        header.setStyleSheet(f"background: {BG_PANEL}; border-bottom: 1px solid {BORDER};")
        hl = QHBoxLayout(header)
        hl.setContentsMargins(16, 0, 16, 0)
        lbl = QLabel(title)
        lbl.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 10px; font-weight: 600;")
        hl.addWidget(lbl)
        hl.addStretch()
        return header

    def _setup_listeners(self):
        """Setup listeners for events."""
        self._events.log_message.connect(self._log_panel.add_log_line)
        self._events.state_changed.connect(self._on_service_state_changed)

    def _on_service_state_changed(self, service_name: str, state_value: str):
        """Called when any service state changes."""
        try:
            state = ServiceState(state_value)
        except ValueError:
            return

        if service_name == "supplier" and service_name in self._supplier_cards:
            card = self._supplier_cards[service_name]
            card.set_loading(state in (ServiceState.STARTING, ServiceState.STOPPING))

    def _check_running_containers(self):
        """Check if there are running containers at startup and sync state."""
        try:
            has_running, has_stopped = self._service_manager.check_and_sync_running_containers()

            if has_running or has_stopped:
                self._popup.show()
                self._popup.raise_()
        except Exception as e:
            logger.warning(f"Error checking containers: {str(e)}")

    def _on_supplier_toggled(self, supplier_id: str, active: bool):
        """Handle supplier toggle."""
        supplier = self._suppliers[supplier_id]

        if active:
            logger.info(f"Starting supplier: {supplier.name}")
            self._service_manager.start_supplier()
        else:
            logger.info(f"Stopping supplier: {supplier.name}")
            self._service_manager.stop_supplier()

    def _on_run_requested(self, consumer_id: str):
        """Handle consumer run request."""
        consumer = self._consumers[consumer_id]
        logger.info(f"Running consumer: {consumer.name}")

    def _on_build_requested(self, supplier_id: str):
        """Handle supplier build request."""
        supplier = self._suppliers[supplier_id]
        logger.info(f"Building supplier: {supplier.name}")
        self._service_manager.build_supplier()

    def _on_stop_all(self):
        """Stop all services."""
        logger.info("Stopping all services")
        self._service_manager.stop_all()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._popup and self._popup.isVisible():
            central = self.centralWidget()
            if central:
                self._popup.setGeometry(central.rect())

    def closeEvent(self, event):
        """Cleanup when closing."""
        logger.info("Closing application")
        super().closeEvent(event)
