"""PyQt6 dashboard: renders Snapshots/Events produced by poller.PollerThread.

Purely observational -- no widget here ever triggers a Redis write.
"""
from __future__ import annotations

import json
import time

from PyQt6.QtCore import QEvent, Qt, QTimer
from PyQt6.QtGui import QFont, QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QAbstractSpinBox,
    QApplication,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPlainTextEdit,
    QSpinBox,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .poller import Event, MethodInfo, PollerThread, Snapshot

WINDOW_TITLE = "AnyCall Visualizer"
MAX_LOG_LINES = 1000
DEFAULT_FONT_SIZE = 12
MIN_FONT_SIZE = 8
MAX_FONT_SIZE = 32

# Explicit dark palette so the dashboard doesn't inherit the system/GTK theme
# (which rendered dark-on-dark text with poor contrast). Values are hand-tuned
# for contrast rather than pulled from a native theme.
_BG = "#1e2228"
_PANEL_BG = "#242932"
_ALT_ROW_BG = "#262b33"
_HEADER_BG = "#2d333d"
_BORDER = "#3a4048"
_TEXT = "#e8eaed"
_TEXT_MUTED = "#9aa4b2"
_ACCENT = "#2f6fed"
_ACCENT_TEXT = "#ffffff"

DARK_STYLESHEET = f"""
QMainWindow, QWidget {{
    background-color: {_BG};
    color: {_TEXT};
}}

QLabel {{
    color: {_TEXT};
    background-color: transparent;
}}

QGroupBox {{
    background-color: {_PANEL_BG};
    border: 1px solid {_BORDER};
    border-radius: 4px;
    margin-top: 10px;
    padding-top: 6px;
}}

QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 8px;
    padding: 0 4px;
    color: {_TEXT};
}}

QTreeWidget, QTreeView {{
    background-color: {_PANEL_BG};
    alternate-background-color: {_ALT_ROW_BG};
    color: {_TEXT};
    border: 1px solid {_BORDER};
    outline: 0;
}}

QTreeWidget::item, QTreeView::item {{
    padding: 2px 0;
}}

QTreeWidget::item:hover, QTreeView::item:hover {{
    background-color: {_ALT_ROW_BG};
}}

QTreeWidget::item:selected, QTreeView::item:selected {{
    background-color: {_ACCENT};
    color: {_ACCENT_TEXT};
}}

QHeaderView::section {{
    background-color: {_HEADER_BG};
    color: {_TEXT};
    border: none;
    border-right: 1px solid {_BORDER};
    border-bottom: 1px solid {_BORDER};
    padding: 4px 6px;
}}

QPlainTextEdit {{
    background-color: {_PANEL_BG};
    color: {_TEXT};
    border: 1px solid {_BORDER};
}}

QSpinBox {{
    background-color: {_PANEL_BG};
    color: {_TEXT};
    border: 1px solid {_BORDER};
    border-radius: 3px;
    padding: 2px 4px;
}}

QSpinBox::up-button, QSpinBox::down-button {{
    width: 0px;
    border: none;
}}

QToolButton#fontStepButton {{
    background-color: {_HEADER_BG};
    color: {_TEXT};
    border: 1px solid {_BORDER};
    border-radius: 3px;
    font-weight: bold;
    padding: 0px;
}}

QToolButton#fontStepButton:hover {{
    background-color: {_ACCENT};
    color: {_ACCENT_TEXT};
}}

QToolButton#fontStepButton:pressed {{
    background-color: {_ACCENT};
}}

QScrollBar:vertical, QScrollBar:horizontal {{
    background-color: {_PANEL_BG};
    border: none;
}}

QScrollBar::handle {{
    background-color: {_BORDER};
    border-radius: 3px;
}}

QScrollBar::handle:hover {{
    background-color: {_TEXT_MUTED};
}}

QToolTip {{
    background-color: {_HEADER_BG};
    color: {_TEXT};
    border: 1px solid {_BORDER};
}}
"""

# Item geometry at DEFAULT_FONT_SIZE, scaled proportionally with the chosen
# size so surrounding columns grow with the text instead of leaving bigger
# glyphs cramped inside fixed-size columns.
METHODS_TREE_BASE_COLUMNS = {0: 340, 1: 80, 2: 90, 3: 90}
TREE_BASE_INDENT = 20

# Custom item-data roles: KEY_ROLE holds a stable string identifying the row
# (survives tree rebuilds, unlike the QTreeWidgetItem instance itself) so
# selection/expand state can be restored after every poll; DATA_ROLE holds
# the row's full JSON-serializable dict, backing Ctrl-C copy.
KEY_ROLE = Qt.ItemDataRole.UserRole
DATA_ROLE = Qt.ItemDataRole.UserRole + 1


class VisualizerApp(QMainWindow):
    def __init__(self, redis_uri: str, interval: float = 1.0):
        super().__init__()
        self.setWindowTitle(WINDOW_TITLE)
        self.resize(1200, 760)
        self.setStyleSheet(DARK_STYLESHEET)

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
        # Native up/down arrows render as blank boxes under this theme's
        # stylesheet on some Qt styles, so the spin buttons are hidden and
        # replaced with explicit -/+ buttons below.
        self._font_size_spin.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self._font_size_spin.valueChanged.connect(self._apply_font_size)
        header.addWidget(self._font_size_spin)
        self._font_dec_button = self._make_font_step_button("−", -1)
        header.addWidget(self._font_dec_button)
        self._font_inc_button = self._make_font_step_button("+", 1)
        header.addWidget(self._font_inc_button)
        layout.addLayout(header)

        self._methods_group = QGroupBox("Methods (request queues)")
        methods_layout = QVBoxLayout(self._methods_group)
        self._methods_tree = QTreeWidget()
        self._methods_tree.setColumnCount(2)
        self._methods_tree.setHeaderLabels(["method", "backlog"])
        self._methods_tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._methods_tree.setUniformRowHeights(True)
        self._methods_tree.setAlternatingRowColors(True)
        methods_layout.addWidget(self._methods_tree)
        self._bind_copy_json(self._methods_tree)
        layout.addWidget(self._methods_group, 1)

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

    # -- Ctrl-C copy-as-JSON --------------------------------------------------

    def _bind_copy_json(self, tree: QTreeWidget) -> None:
        shortcut = QShortcut(QKeySequence.StandardKey.Copy, tree)
        shortcut.setContext(Qt.ShortcutContext.WidgetShortcut)
        shortcut.activated.connect(lambda t=tree: self._copy_selection_as_json(t))

    def _copy_selection_as_json(self, tree: QTreeWidget) -> None:
        # If a selected row's ancestor is also selected, drop the descendant --
        # otherwise its data would show up twice in the output. No tree nests
        # today, but this stays correct if one ever does again.
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
            "kind": method.kind,
            "backlog": method.backlog,
        }

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
                [
                    f"{method.name}  [{method.kind}]",
                    str(method.backlog),
                ]
            )
            method_item.setData(0, KEY_ROLE, method_key)
            method_item.setData(0, DATA_ROLE, self._method_to_dict(method))
            self._set_numeric_columns(method_item, range(1, 2))

            top_items.append(method_item)

        tree.addTopLevelItems(top_items)
        self._restore_tree_state(tree, selected, expanded, current)

    def _append_events(self, events: list[Event]) -> None:
        for event in events:
            ts = time.strftime("%H:%M:%S", time.localtime(event.timestamp))
            self._log_text.appendPlainText(f"[{ts}] {event.message}")
        scrollbar = self._log_text.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    # -- font size -------------------------------------------------------------

    def _make_font_step_button(self, label: str, step: int) -> QToolButton:
        button = QToolButton()
        button.setObjectName("fontStepButton")
        button.setText(label)
        button.setAutoRepeat(True)
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        button.clicked.connect(lambda: self._apply_font_size(self._font_size_spin.value() + step))
        return button

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
            self._log_group,
        ):
            widget.setFont(base_font)
        self._status_label.setFont(bold_font)

        spin_height = self._font_size_spin.sizeHint().height()
        for button in (self._font_dec_button, self._font_inc_button):
            button.setFont(bold_font)
            button.setFixedSize(spin_height, spin_height)

        self._methods_tree.setFont(base_font)
        self._methods_tree.header().setFont(bold_font)

        self._log_text.setFont(mono_font)
        if not hasattr(self, "_log_height_set"):
            self._log_text.setFixedHeight(self._log_text.fontMetrics().lineSpacing() * 12 + 12)
            self._log_height_set = True

        scale = size / DEFAULT_FONT_SIZE
        self._methods_tree.setIndentation(round(TREE_BASE_INDENT * scale))
        for column, base_width in METHODS_TREE_BASE_COLUMNS.items():
            self._methods_tree.setColumnWidth(column, round(base_width * scale))

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
