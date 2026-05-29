import uuid
import random
import datetime
import subprocess
import os

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QLabel,
    QScrollArea, QFrame, QSplitter,
)
from PySide6.QtCore import Qt, QTimer

from app.models import MOCK_SUPPLIERS, MOCK_CONSUMERS, Supplier, Consumer, ExecutionResult
from app.theme import BG_PANEL, BORDER, TEXT_MUTED, PANEL_WIDTH
from app.widgets.supplier_card import SupplierCard
from app.widgets.consumer_card import ConsumerCard
from app.widgets.log_panel import LogPanel
from app.widgets.container_warning_popup import ContainerWarningPopup


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("AnyCall Profiling Tool")
        self.resize(1100, 700)
        self.setMinimumSize(820, 520)

        self._suppliers: dict[str, Supplier] = {s.id: s for s in MOCK_SUPPLIERS}
        self._consumers: dict[str, Consumer] = {c.id: c for c in MOCK_CONSUMERS}
        self._supplier_cards: dict[str, SupplierCard] = {}
        self._consumer_cards: dict[str, ConsumerCard] = {}

        self._build_ui()
        QTimer.singleShot(500, self._check_running_containers)

    # ------------------------------------------------------------------ build

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)

        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Left panel: Suppliers and Consumers (vertical splitter)
        root.addWidget(self._build_left_panel(central))

        divider = QFrame()
        divider.setFixedWidth(1)
        divider.setStyleSheet(f"background: {BORDER};")
        root.addWidget(divider)

        # Right panel: Execution Log
        root.addWidget(self._build_right_panel(central), stretch=1)

        # Popup overlay
        self._popup = ContainerWarningPopup(central)
        self._popup.confirmed.connect(lambda: self._on_stop_containers(self._root_dir))
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

        # ── suppliers ──────────────────────────────────────────────────
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
            self._supplier_cards[supplier.id] = card
            vbox.addWidget(card)

        vbox.addStretch()
        scroll.setWidget(container)
        sl.addWidget(scroll)

        # ── consumers ──────────────────────────────────────────────────
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

        splitter.addWidget(suppliers_widget)
        splitter.addWidget(consumers_widget)
        splitter.setSizes([220, 280])

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
        header.setStyleSheet(
            f"background: {BG_PANEL}; border-bottom: 1px solid {BORDER};"
        )
        hl = QHBoxLayout(header)
        hl.setContentsMargins(16, 0, 16, 0)
        lbl = QLabel(title)
        lbl.setStyleSheet(
            f"color: {TEXT_MUTED}; font-size: 10px; font-weight: 600;"
        )
        hl.addWidget(lbl)
        hl.addStretch()
        return header

    def _check_running_containers(self):
        try:
            self._root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            result = subprocess.run(
                ["docker", "compose", "ps", "--quiet"],
                cwd=self._root_dir,
                capture_output=True,
                text=True,
                timeout=5,
            )

            running_containers = result.stdout.strip()
            if running_containers:
                self._popup.show()
                self._popup.raise_()
        except Exception:
            pass

    def _on_stop_containers(self, root_dir: str):
        try:
            subprocess.run(
                ["docker", "compose", "down"],
                cwd=root_dir,
                capture_output=True,
                timeout=30,
            )
        except Exception:
            pass

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._popup and self._popup.isVisible():
            central = self.centralWidget()
            if central:
                self._popup.setGeometry(central.rect())

    # --------------------------------------------------------------- handlers

    def _on_run_requested(self, consumer_id: str):
        consumer = self._consumers[consumer_id]
        supplier = self._suppliers[consumer.supplier_id]

        duration = random.randint(4, 80)
        now = datetime.datetime.now()
        ts = lambda: now.strftime("%H:%M:%S.%f")[:-3]
        rid = str(uuid.uuid4())[:8]

        lines = [
            f"# {consumer.name}  ·  {consumer.language.upper()}  →  {supplier.name}",
            f"# {now.strftime('%Y-%m-%d %H:%M:%S')}",
            "",
            f"[{ts()}] [CLIENT] Iniciando chamada: {consumer.method}()",
            f"[{ts()}] [CLIENT] Serializando request payload...",
            f"[{ts()}] [REQUEST] XADD  stream={supplier.name}  requestId={rid}",
            f"[{ts()}] [CLIENT] Aguardando response  (timeout=30s)  ·  XREAD BLOCK",
            "",
            f"[{ts()}] [SERVER] XREADGROUP — nova mensagem recebida",
            f"[{ts()}] [SERVER] Deserializando payload ({random.randint(1,4)}ms)",
            f"[{ts()}] [SERVER] {consumer.method}() executado em {random.randint(2,15)}ms",
            f"[{ts()}] [SERVER] XADD response stream  ·  {random.randint(0,2)}ms",
            "",
            f"[{ts()}] [RESPONSE] received in {duration}ms",
            f"[{ts()}] [CLIENT] Deserializando response...",
            f"[{ts()}] [CLIENT] OK — {self._mock_payload(consumer.method)}",
        ]

        self._log_panel.show_result(
            ExecutionResult(
                consumer=consumer,
                supplier=supplier,
                duration_ms=duration,
                lines=lines,
                success=True,
            )
        )

    def _mock_payload(self, method: str) -> str:
        return {
            "createProduct": '{"id": 42, "name": "Widget X", "price": 19.99}',
            "createOrder":   '{"orderId": 1001, "status": "PENDING", "total": 89.90}',
            "checkStock":    '{"sku": "WGT-X", "available": 150, "reserved": 12}',
        }.get(method, '{"result": "ok"}')

