"""PyQt6 dashboard: renders Snapshots/Events produced by poller.PollerThread.

Purely observational -- no widget here ever triggers a Redis write.
"""
from __future__ import annotations

import json
import time
from dataclasses import asdict

from PyQt6.QtCore import QEvent, Qt, QTimer
from PyQt6.QtGui import QFont, QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPlainTextEdit,
    QSpinBox,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .poller import ConsumerInfo, Event, GroupInfo, MethodInfo, PollerThread, ServerInfo, Snapshot

WINDOW_TITLE = "AnyCall Visualizer"
MAX_LOG_LINES = 1000
DEFAULT_FONT_SIZE = 12
MIN_FONT_SIZE = 8
MAX_FONT_SIZE = 32

# Item geometry at DEFAULT_FONT_SIZE, scaled proportionally with the chosen
# size so surrounding columns grow with the text instead of leaving bigger
# glyphs cramped inside fixed-size columns.
METHODS_TREE_BASE_COLUMNS = {0: 340, 1: 80, 2: 90, 3: 90}
SERVERS_TREE_BASE_COLUMNS = {0: 220, 1: 110, 2: 90}
TREE_BASE_INDENT = 20

# Custom item-data roles: KEY_ROLE holds a stable string identifying the row
# (survives tree rebuilds, unlike the QTreeWidgetItem instance itself) so
# selection/expand state can be restored after every poll; DATA_ROLE holds
# the row's full JSON-serializable dict, backing Ctrl-C copy.
KEY_ROLE = Qt.ItemDataRole.UserRole
DATA_ROLE = Qt.ItemDataRole.UserRole + 1


def _age(epoch_seconds: float, now: float) -> str:
    if epoch_seconds <= 0:
        return "?"
    delta = max(0, now - epoch_seconds)
    if delta < 60:
        return f"{delta:.0f}s ago"
    return f"{delta / 60:.1f}m ago"


class VisualizerApp(QMainWindow):
    def __init__(self, redis_uri: str, interval: float = 1.0):
        super().__init__()
        self.setWindowTitle(WINDOW_TITLE)
        self.resize(1200, 760)

        self._build_widgets(redis_uri)
        self._apply_font_size(DEFAULT_FONT_SIZE)
        # QLabel/QGroupBox/empty tree area don't accept focus, so clicking
        # them doesn't naturally move focus away from the spin box the way
        # clicking another focusable widget would -- catch clicks globally
        # instead so "click elsewhere" always deselects the font size field.
        QApplication.instance().installEventFilter(self)

        self._poller = PollerThread(redis_uri, interval=interval, parent=self)
        self._poller.snapshot_ready.connect(self._on_snapshot)
        self._poller.start()

    # -- widget construction -------------------------------------------------

    def _build_widgets(self, redis_uri: str) -> None:
        central = QWidget(self)
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(10, 8, 10, 10)

        header = QHBoxLayout()
        self._status_label = QLabel(f"connecting to {redis_uri} ...")
        header.addWidget(self._status_label)
        header.addStretch(1)
        self._stats_label = QLabel("")
        header.addWidget(self._stats_label)
        header.addSpacing(16)
        self._font_label = QLabel("Font size:")
        header.addWidget(self._font_label)
        self._font_size_spin = QSpinBox()
        self._font_size_spin.setRange(MIN_FONT_SIZE, MAX_FONT_SIZE)
        self._font_size_spin.setValue(DEFAULT_FONT_SIZE)
        self._font_size_spin.valueChanged.connect(self._apply_font_size)
        header.addWidget(self._font_size_spin)
        layout.addLayout(header)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        self._methods_group = QGroupBox("Methods (request streams)")
        methods_layout = QVBoxLayout(self._methods_group)
        self._methods_tree = QTreeWidget()
        self._methods_tree.setColumnCount(4)
        self._methods_tree.setHeaderLabels(["method / group / consumer", "backlog", "processing", "consumers"])
        self._methods_tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._methods_tree.setUniformRowHeights(True)
        methods_layout.addWidget(self._methods_tree)
        splitter.addWidget(self._methods_group)
        self._bind_copy_json(self._methods_tree)

        self._servers_group = QGroupBox("Servers (heartbeats)")
        servers_layout = QVBoxLayout(self._servers_group)
        self._servers_tree = QTreeWidget()
        self._servers_tree.setColumnCount(3)
        self._servers_tree.setHeaderLabels(["server id", "last heartbeat", "expires in"])
        self._servers_tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._servers_tree.setUniformRowHeights(True)
        servers_layout.addWidget(self._servers_tree)
        splitter.addWidget(self._servers_group)
        self._bind_copy_json(self._servers_tree)

        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        layout.addWidget(splitter, 1)

        self._log_group = QGroupBox("Activity log")
        log_layout = QVBoxLayout(self._log_group)
        self._log_text = QPlainTextEdit()
        self._log_text.setReadOnly(True)
        self._log_text.setMaximumBlockCount(MAX_LOG_LINES)
        self._log_text.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        log_layout.addWidget(self._log_text)
        layout.addWidget(self._log_group)

    # -- update loop -----------------------------------------------------------

    def _on_snapshot(self, snapshot: Snapshot, events: list[Event]) -> None:
        self._render_snapshot(snapshot)
        if events:
            self._append_events(events)

    def _render_snapshot(self, snapshot: Snapshot) -> None:
        if not snapshot.connected:
            self._status_label.setText(f"⚠ disconnected from {snapshot.redis_uri}: {snapshot.error}")
            self._stats_label.setText("")
            return

        self._status_label.setText(f"● connected to {snapshot.redis_uri}")
        self._stats_label.setText(
            f"redis {snapshot.redis_version}  |  clients {snapshot.connected_clients}  |  "
            f"memory {snapshot.used_memory_human}  |  awaiting delivery {snapshot.inflight_responses}"
        )

        self._render_methods(snapshot)
        self._render_servers(snapshot)

    # -- Ctrl-C copy-as-JSON --------------------------------------------------

    def _bind_copy_json(self, tree: QTreeWidget) -> None:
        shortcut = QShortcut(QKeySequence.StandardKey.Copy, tree)
        shortcut.setContext(Qt.ShortcutContext.WidgetShortcut)
        shortcut.activated.connect(lambda t=tree: self._copy_selection_as_json(t))

    def _copy_selection_as_json(self, tree: QTreeWidget) -> None:
        # A selected group already nests its consumers (same for a selected
        # method nesting its groups), so if both are selected together, drop
        # the descendant -- otherwise its data shows up twice in the output.
        selected_items = tree.selectedItems()
        selected_keys = {item.data(0, KEY_ROLE) for item in selected_items}

        def has_selected_ancestor(item: QTreeWidgetItem) -> bool:
            parent = item.parent()
            while parent is not None:
                if parent.data(0, KEY_ROLE) in selected_keys:
                    return True
                parent = parent.parent()
            return False

        top_level = [item for item in selected_items if not has_selected_ancestor(item)]
        items = [item.data(0, DATA_ROLE) for item in top_level]
        if not items:
            return

        payload = items[0] if len(items) == 1 else items
        QApplication.clipboard().setText(json.dumps(payload, indent=2, ensure_ascii=False))

        self.setWindowTitle(f"{WINDOW_TITLE} — copied {len(items)} row(s) as JSON")
        QTimer.singleShot(1500, lambda: self.setWindowTitle(WINDOW_TITLE))

    @staticmethod
    def _method_to_dict(method: MethodInfo) -> dict:
        return {
            "method": method.name,
            "backlog": method.backlog,
            "processing": method.processing,
            "consumer_count": method.consumer_count,
            "groups": [VisualizerApp._group_to_dict(g) for g in method.groups],
        }

    @staticmethod
    def _group_to_dict(group: GroupInfo, method_name: str | None = None) -> dict:
        d = {"group": group.name, "pending": group.pending, "consumers": [asdict(c) for c in group.consumers]}
        if method_name is not None:
            d = {"method": method_name, **d}
        return d

    @staticmethod
    def _consumer_to_dict(consumer: ConsumerInfo, method_name: str, group_name: str) -> dict:
        return {"method": method_name, "group": group_name, **asdict(consumer)}

    @staticmethod
    def _server_to_dict(server: ServerInfo) -> dict:
        return asdict(server)

    # -- tree state preservation across rebuilds ------------------------------

    @staticmethod
    def _capture_tree_state(tree: QTreeWidget) -> tuple[set[str], set[str], str | None]:
        selected: set[str] = set()
        expanded: set[str] = set()

        def walk(item: QTreeWidgetItem) -> None:
            key = item.data(0, KEY_ROLE)
            if item.isSelected():
                selected.add(key)
            if item.isExpanded():
                expanded.add(key)
            for i in range(item.childCount()):
                walk(item.child(i))

        for i in range(tree.topLevelItemCount()):
            walk(tree.topLevelItem(i))

        current_item = tree.currentItem()
        current = current_item.data(0, KEY_ROLE) if current_item is not None else None
        return selected, expanded, current

    @staticmethod
    def _restore_tree_state(tree: QTreeWidget, selected: set[str], expanded: set[str], current: str | None) -> None:
        def walk(item: QTreeWidgetItem) -> None:
            key = item.data(0, KEY_ROLE)
            if key in expanded:
                item.setExpanded(True)
            if key in selected:
                item.setSelected(True)
            if key == current:
                tree.setCurrentItem(item)
            for i in range(item.childCount()):
                walk(item.child(i))

        for i in range(tree.topLevelItemCount()):
            walk(tree.topLevelItem(i))

    @staticmethod
    def _set_numeric_columns(item: QTreeWidgetItem, columns: range) -> None:
        for column in columns:
            item.setTextAlignment(column, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

    def _render_methods(self, snapshot: Snapshot) -> None:
        tree = self._methods_tree
        selected, expanded, current = self._capture_tree_state(tree)
        tree.clear()

        top_items = []
        for method in snapshot.methods:
            method_key = f"method:{method.name}"
            method_item = QTreeWidgetItem(
                [method.name, str(method.backlog), str(method.processing), str(method.consumer_count)]
            )
            method_item.setData(0, KEY_ROLE, method_key)
            method_item.setData(0, DATA_ROLE, self._method_to_dict(method))
            self._set_numeric_columns(method_item, range(1, 4))

            for group in method.groups:
                group_key = f"{method_key}:group:{group.name}"
                group_item = QTreeWidgetItem(
                    [f"group: {group.name}", "", str(group.pending), str(len(group.consumers))]
                )
                group_item.setData(0, KEY_ROLE, group_key)
                group_item.setData(0, DATA_ROLE, self._group_to_dict(group, method.name))
                self._set_numeric_columns(group_item, range(1, 4))

                for consumer in group.consumers:
                    consumer_key = f"{group_key}:consumer:{consumer.name}"
                    consumer_item = QTreeWidgetItem(
                        [f"consumer: {consumer.name}  (idle {consumer.idle_ms} ms)", "", str(consumer.pending), ""]
                    )
                    consumer_item.setData(0, KEY_ROLE, consumer_key)
                    consumer_item.setData(0, DATA_ROLE, self._consumer_to_dict(consumer, method.name, group.name))
                    self._set_numeric_columns(consumer_item, range(1, 4))
                    group_item.addChild(consumer_item)

                method_item.addChild(group_item)

            top_items.append(method_item)

        tree.addTopLevelItems(top_items)
        self._restore_tree_state(tree, selected, expanded, current)

    def _render_servers(self, snapshot: Snapshot) -> None:
        now = time.time()
        tree = self._servers_tree
        selected, expanded, current = self._capture_tree_state(tree)
        tree.clear()

        top_items = []
        for server in snapshot.servers:
            item = QTreeWidgetItem([server.server_id, _age(server.last_heartbeat_epoch, now), f"{server.ttl_seconds}s"])
            item.setData(0, KEY_ROLE, server.key)
            item.setData(0, DATA_ROLE, self._server_to_dict(server))
            self._set_numeric_columns(item, range(1, 3))
            top_items.append(item)

        tree.addTopLevelItems(top_items)
        self._restore_tree_state(tree, selected, expanded, current)

    def _append_events(self, events: list[Event]) -> None:
        for event in events:
            ts = time.strftime("%H:%M:%S", time.localtime(event.timestamp))
            self._log_text.appendPlainText(f"[{ts}] {event.message}")
        scrollbar = self._log_text.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    # -- font size -------------------------------------------------------------

    def _apply_font_size(self, size: int) -> None:
        size = max(MIN_FONT_SIZE, min(MAX_FONT_SIZE, size))
        if size != self._font_size_spin.value():
            self._font_size_spin.setValue(size)

        base_font = QFont()
        base_font.setPointSize(size)
        bold_font = QFont(base_font)
        bold_font.setBold(True)
        mono_font = QFont("Monospace")
        mono_font.setStyleHint(QFont.StyleHint.TypeWriter)
        mono_font.setPointSize(size)

        for widget in (
            self._stats_label,
            self._font_label,
            self._font_size_spin,
            self._methods_group,
            self._servers_group,
            self._log_group,
        ):
            widget.setFont(base_font)
        self._status_label.setFont(bold_font)

        for tree in (self._methods_tree, self._servers_tree):
            tree.setFont(base_font)
            tree.header().setFont(bold_font)

        self._log_text.setFont(mono_font)
        if not hasattr(self, "_log_height_set"):
            self._log_text.setFixedHeight(self._log_text.fontMetrics().lineSpacing() * 12 + 12)
            self._log_height_set = True

        scale = size / DEFAULT_FONT_SIZE
        self._methods_tree.setIndentation(round(TREE_BASE_INDENT * scale))
        self._servers_tree.setIndentation(round(TREE_BASE_INDENT * scale))
        for tree, base_columns in (
            (self._methods_tree, METHODS_TREE_BASE_COLUMNS),
            (self._servers_tree, SERVERS_TREE_BASE_COLUMNS),
        ):
            for column, base_width in base_columns.items():
                tree.setColumnWidth(column, round(base_width * scale))

    def eventFilter(self, obj, event) -> bool:  # noqa: N802 (Qt override)
        if event.type() == QEvent.Type.MouseButtonPress:
            spin = self._font_size_spin
            if spin.hasFocus() and obj is not spin and obj is not spin.lineEdit():
                spin.clearFocus()
                spin.lineEdit().deselect()
        return super().eventFilter(obj, event)

    # -- shutdown ----------------------------------------------------------------

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt override)
        QApplication.instance().removeEventFilter(self)
        self._poller.stop()
        self._poller.wait(2000)
        super().closeEvent(event)
