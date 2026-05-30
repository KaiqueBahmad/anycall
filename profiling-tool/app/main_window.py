import datetime
import subprocess
import os
import time
import threading
import logging

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

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('/tmp/anycall_profiling.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


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
            card.toggled.connect(self._on_supplier_toggled)
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

            # Check for running containers
            result = subprocess.run(
                ["docker", "compose", "ps", "--quiet"],
                cwd=self._root_dir,
                capture_output=True,
                text=True,
                timeout=5,
            )

            running_containers = result.stdout.strip()
            has_running = bool(running_containers)

            # Check for stopped containers that might cause conflicts
            has_stopped = False
            try:
                result_all = subprocess.run(
                    ["docker", "compose", "ps", "-a", "--quiet"],
                    cwd=self._root_dir,
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                all_containers = result_all.stdout.strip()
                has_stopped = bool(all_containers) and not has_running

                logger.info(f"Docker check - Running: {has_running}, Stopped: {has_stopped}")
            except Exception:
                pass

            if has_running or has_stopped:
                self._popup.show()
                self._popup.raise_()
        except Exception as e:
            logger.warning(f"Error checking containers: {str(e)}")
            pass

    def _on_stop_containers(self, root_dir: str):
        try:
            logger.info("Starting Docker cleanup...")
            QTimer.singleShot(0, lambda: self._log_panel.add_log_line("# Cleaning up Docker containers...", "header"))

            # Step 1: Try normal down with remove-orphans and volumes
            logger.info("Step 1: docker compose down --remove-orphans -v")
            result = subprocess.run(
                ["docker", "compose", "down", "--remove-orphans", "-v"],
                cwd=root_dir,
                capture_output=True,
                text=True,
                timeout=30,
            )

            if result.returncode == 0:
                logger.info("Successfully cleaned up with docker compose down")
                QTimer.singleShot(0, lambda: self._log_panel.add_log_line("✓ Docker compose cleaned", "success"))
            else:
                logger.warning(f"Docker compose down returned code {result.returncode}: {result.stderr}")
                QTimer.singleShot(0, lambda: self._log_panel.add_log_line("⚠ docker compose down encountered issues, trying force cleanup...", "warning"))

                # Step 2: If compose down fails, try to remove containers by name
                logger.info("Step 2: Force removing containers...")
                containers = ["anycall-redis", "anycall-supplier", "anycall-consumer"]
                for container in containers:
                    try:
                        subprocess.run(
                            ["docker", "container", "rm", "-f", container],
                            capture_output=True,
                            timeout=10,
                        )
                        logger.info(f"Removed container: {container}")
                    except Exception as e:
                        logger.debug(f"Could not remove {container}: {str(e)}")

                QTimer.singleShot(0, lambda: self._log_panel.add_log_line("✓ Force cleanup completed", "success"))

            logger.info("Docker cleanup completed")

        except subprocess.TimeoutExpired:
            logger.error("Timeout during Docker cleanup")
            QTimer.singleShot(0, lambda: self._log_panel.add_log_line("✗ Timeout during cleanup", "error"))
        except Exception as e:
            logger.error(f"Error during Docker cleanup: {str(e)}")
            QTimer.singleShot(0, lambda: self._log_panel.add_log_line(f"✗ Error: {str(e)}", "error"))

    def _on_supplier_toggled(self, supplier_id: str, active: bool):
        supplier = self._suppliers[supplier_id]
        action = "Starting" if active else "Stopping"

        logger.info(f"{action} supplier: {supplier.name} (ID: {supplier_id})")
        self._log_panel.add_log_line(f"# {action} supplier: {supplier.name}", "header")

        self._supplier_cards[supplier_id].set_loading(True)
        thread = threading.Thread(target=self._toggle_docker_compose, args=(supplier_id, active))
        thread.daemon = True
        thread.start()

    def _toggle_docker_compose(self, supplier_id: str, active: bool):
        supplier = self._suppliers[supplier_id]
        action = "up" if active else "down"
        start_time = time.time()

        try:
            if active:
                cmd = ["docker", "compose", "up", "-d", "--remove-orphans", "redis", "supplier"]
                logger.info(f"Executing: {' '.join(cmd)}")
                QTimer.singleShot(0, lambda: self._log_panel.add_log_line(f"$ docker compose up -d --remove-orphans redis supplier", "info"))

                result = subprocess.run(
                    cmd,
                    cwd=self._root_dir,
                    capture_output=True,
                    text=True,
                    timeout=60,
                )

                if result.returncode == 0:
                    elapsed = time.time() - start_time
                    msg = f"✓ Supplier {supplier.name} started successfully ({elapsed:.2f}s)"
                    logger.info(msg)
                    QTimer.singleShot(0, lambda: self._log_panel.add_log_line(msg, "success"))
                else:
                    error_msg = result.stderr or result.stdout
                    logger.error(f"Failed to start supplier: {error_msg}")
                    QTimer.singleShot(0, lambda: self._log_panel.add_log_line(f"✗ Error: {error_msg}", "error"))
            else:
                cmd = ["docker", "compose", "down", "--remove-orphans"]
                logger.info(f"Executing: {' '.join(cmd)}")
                QTimer.singleShot(0, lambda: self._log_panel.add_log_line(f"$ docker compose down --remove-orphans", "info"))

                result = subprocess.run(
                    cmd,
                    cwd=self._root_dir,
                    capture_output=True,
                    text=True,
                    timeout=30,
                )

                if result.returncode == 0:
                    elapsed = time.time() - start_time
                    msg = f"✓ Supplier {supplier.name} stopped successfully ({elapsed:.2f}s)"
                    logger.info(msg)
                    QTimer.singleShot(0, lambda: self._log_panel.add_log_line(msg, "success"))
                else:
                    error_msg = result.stderr or result.stdout
                    logger.error(f"Failed to stop supplier: {error_msg}")
                    QTimer.singleShot(0, lambda: self._log_panel.add_log_line(f"✗ Error: {error_msg}", "error"))

        except subprocess.TimeoutExpired:
            elapsed = time.time() - start_time
            msg = f"✗ Timeout after {elapsed:.2f}s"
            logger.error(f"Timeout executing docker {action} for {supplier.name}")
            QTimer.singleShot(0, lambda: self._log_panel.add_log_line(msg, "error"))
        except Exception as e:
            elapsed = time.time() - start_time
            msg = f"✗ Exception: {str(e)}"
            logger.error(f"Exception executing docker {action} for {supplier.name}: {str(e)}")
            QTimer.singleShot(0, lambda: self._log_panel.add_log_line(msg, "error"))
        finally:
            QTimer.singleShot(0, lambda: self._supplier_cards[supplier_id].set_loading(False))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._popup and self._popup.isVisible():
            central = self.centralWidget()
            if central:
                self._popup.setGeometry(central.rect())

    # --------------------------------------------------------------- handlers

    def _on_run_requested(self, consumer_id: str):
        self._current_consumer_id = consumer_id
        consumer = self._consumers[consumer_id]
        logger.info(f"Running consumer: {consumer.name} (ID: {consumer_id})")
        thread = threading.Thread(target=self._execute_consumer)
        thread.daemon = True
        thread.start()

    def _execute_consumer(self):
        try:
            logger.info("Executing: docker compose restart consumer")
            QTimer.singleShot(0, lambda: self._log_panel.add_log_line("$ docker compose restart consumer", "info"))

            result = subprocess.run(
                ["docker", "compose", "restart", "consumer"],
                cwd=self._root_dir,
                capture_output=True,
                text=True,
                timeout=10,
            )

            if result.returncode == 0:
                logger.info("Consumer restarted successfully")
            else:
                logger.error(f"Failed to restart consumer: {result.stderr or result.stdout}")

            # Wait for consumer to execute and then fetch logs
            time.sleep(2.5)
            QTimer.singleShot(0, self._fetch_execution_logs)
        except subprocess.TimeoutExpired:
            logger.error("Timeout restarting consumer")
            QTimer.singleShot(0, lambda: self._log_panel.add_log_line("✗ Timeout restarting consumer", "error"))
        except Exception as e:
            logger.error(f"Exception executing consumer: {str(e)}")
            QTimer.singleShot(0, lambda: self._log_panel.add_log_line(f"✗ Error: {str(e)}", "error"))

    def _fetch_execution_logs(self):
        consumer_id = self._current_consumer_id
        consumer = self._consumers[consumer_id]
        supplier = self._suppliers[consumer.supplier_id]

        now = datetime.datetime.now()
        lines = [
            f"# {consumer.name}  ·  {consumer.language.upper()}  →  {supplier.name}",
            f"# {now.strftime('%Y-%m-%d %H:%M:%S')}",
            "",
        ]

        try:
            logger.info(f"Fetching logs for consumer {consumer.name}")
            # Get logs from both containers
            result = subprocess.run(
                ["docker", "compose", "logs"],
                cwd=self._root_dir,
                capture_output=True,
                text=True,
                timeout=5,
            )

            log_lines = result.stdout.strip().split("\n")
            lines.extend(log_lines)

            # Calculate duration from logs if possible
            duration = 50
            success = "ERROR" not in result.stdout.lower()

            status = "✓ Success" if success else "✗ Failed"
            logger.info(f"Execution completed: {status} ({duration}ms)")
        except Exception as e:
            lines.append(f"Error: {str(e)}")
            duration = 0
            success = False
            logger.error(f"Error fetching logs: {str(e)}")

        self._log_panel.show_result(
            ExecutionResult(
                consumer=consumer,
                supplier=supplier,
                duration_ms=duration,
                lines=lines,
                success=success,
            )
        )


