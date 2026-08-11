"""Tkinter dashboard: renders Snapshots/Events produced by poller.PollerThread.

Purely observational -- no widget here ever triggers a Redis write.
"""
from __future__ import annotations

import json
import queue
import time
import tkinter as tk
import tkinter.font as tkfont
from dataclasses import asdict
from tkinter import ttk
from typing import Callable

from .poller import ConsumerInfo, Event, GroupInfo, MethodInfo, PollerThread, ServerInfo, Snapshot

MAX_LOG_LINES = 1000
DRAIN_INTERVAL_MS = 150
DEFAULT_FONT_SIZE = 16
MIN_FONT_SIZE = 8
MAX_FONT_SIZE = 32

# Overriding these (rather than just handing font= to the widgets we build
# ourselves) also resizes chrome we don't touch directly -- LabelFrame
# captions, Spinbox/Entry text -- since ttk's default styles point at these
# named fonts. Tk bakes point size to pixels at font-configure time, not at
# draw time, so this must be redone on every size change, not just at startup.
NAMED_FONTS_TO_SCALE = ("TkDefaultFont", "TkTextFont", "TkHeadingFont", "TkMenuFont", "TkFixedFont")

# Pixel geometry at DEFAULT_FONT_SIZE, scaled proportionally with the chosen
# size so surrounding boxes grow with the text instead of leaving bigger
# glyphs cramped inside fixed-size columns.
METHODS_TREE_BASE_COLUMNS = {"#0": 340, "backlog": 80, "processing": 90, "consumers": 90}
SERVERS_TREE_BASE_COLUMNS = {"#0": 220, "last_heartbeat": 110, "ttl": 90}
TREE_BASE_INDENT = 20


def _age(epoch_seconds: float, now: float) -> str:
    if epoch_seconds <= 0:
        return "?"
    delta = max(0, now - epoch_seconds)
    if delta < 60:
        return f"{delta:.0f}s ago"
    return f"{delta / 60:.1f}m ago"


class VisualizerApp(tk.Tk):
    def __init__(self, redis_uri: str, interval: float = 1.0):
        super().__init__()
        self.title("AnyCall Visualizer")
        self.geometry("1200x760")

        self._queue: "queue.Queue" = queue.Queue()
        self._poller = PollerThread(redis_uri, self._queue, interval=interval)
        # Fixed start point of the current Shift-Up/Down range-select run, per
        # tree; ttk.Treeview has no built-in keyboard range selection.
        self._select_anchor: dict[ttk.Treeview, str] = {}
        # iid -> JSON-serializable dict for the row's underlying data, rebuilt
        # on every render; backs Ctrl-C copy since the tree only stores
        # rendered text/columns, not the source objects.
        self._methods_row_data: dict[str, object] = {}
        self._servers_row_data: dict[str, object] = {}

        # In-memory only -- never written to disk, so it resets to
        # DEFAULT_FONT_SIZE on every launch.
        self._font_size_var = tk.IntVar(value=DEFAULT_FONT_SIZE)
        self._named_fonts = {name: tkfont.nametofont(name) for name in NAMED_FONTS_TO_SCALE}
        self._bold_font = tkfont.Font(family=self._named_fonts["TkDefaultFont"].actual("family"), weight="bold")
        self._mono_font = tkfont.Font(family="Courier")
        self._style = ttk.Style(self)

        self._build_widgets(redis_uri)
        self._apply_font_size(DEFAULT_FONT_SIZE)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        self._poller.start()
        self.after(DRAIN_INTERVAL_MS, self._drain_queue)

    # -- widget construction -------------------------------------------------

    def _build_widgets(self, redis_uri: str) -> None:
        self._style.configure("Treeview.Heading", font=self._bold_font)

        header = ttk.Frame(self, padding=(10, 8))
        header.pack(side=tk.TOP, fill=tk.X)

        self._status_var = tk.StringVar(value=f"connecting to {redis_uri} ...")
        ttk.Label(header, textvariable=self._status_var, font=self._bold_font).pack(side=tk.LEFT)

        font_frame = ttk.Frame(header)
        font_frame.pack(side=tk.RIGHT)
        ttk.Label(font_frame, text="Font size:").pack(side=tk.LEFT, padx=(0, 4))
        font_spinbox = ttk.Spinbox(
            font_frame,
            from_=MIN_FONT_SIZE,
            to=MAX_FONT_SIZE,
            width=3,
            textvariable=self._font_size_var,
            command=self._on_font_size_change,
        )
        font_spinbox.pack(side=tk.LEFT)
        font_spinbox.bind("<Return>", self._on_font_size_change)
        font_spinbox.bind("<FocusOut>", self._on_font_size_change)

        self._stats_var = tk.StringVar(value="")
        ttk.Label(header, textvariable=self._stats_var).pack(side=tk.RIGHT, padx=(0, 16))

        body = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        body.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=10, pady=(0, 8))

        methods_frame = ttk.LabelFrame(body, text="Methods (request streams)")
        self._methods_tree = ttk.Treeview(
            methods_frame,
            columns=("backlog", "processing", "consumers"),
            show="tree headings",
            selectmode="extended",
        )
        self._methods_tree.heading("#0", text="method / group / consumer")
        self._methods_tree.heading("backlog", text="backlog")
        self._methods_tree.heading("processing", text="processing")
        self._methods_tree.heading("consumers", text="consumers")
        self._methods_tree.column("#0", width=340)
        self._methods_tree.column("backlog", width=80, anchor=tk.E)
        self._methods_tree.column("processing", width=90, anchor=tk.E)
        self._methods_tree.column("consumers", width=90, anchor=tk.E)
        methods_scroll = ttk.Scrollbar(methods_frame, orient=tk.VERTICAL, command=self._methods_tree.yview)
        self._methods_tree.configure(yscrollcommand=methods_scroll.set)
        self._methods_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        methods_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        body.add(methods_frame, weight=3)
        self._bind_range_selection(self._methods_tree)
        self._bind_copy_json(self._methods_tree, lambda: self._methods_row_data)

        servers_frame = ttk.LabelFrame(body, text="Servers (heartbeats)")
        self._servers_tree = ttk.Treeview(
            servers_frame,
            columns=("last_heartbeat", "ttl"),
            show="tree headings",
            selectmode="extended",
        )
        self._servers_tree.heading("#0", text="server id")
        self._servers_tree.heading("last_heartbeat", text="last heartbeat")
        self._servers_tree.heading("ttl", text="expires in")
        self._servers_tree.column("#0", width=220)
        self._servers_tree.column("last_heartbeat", width=110, anchor=tk.E)
        self._servers_tree.column("ttl", width=90, anchor=tk.E)
        servers_scroll = ttk.Scrollbar(servers_frame, orient=tk.VERTICAL, command=self._servers_tree.yview)
        self._servers_tree.configure(yscrollcommand=servers_scroll.set)
        self._servers_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        servers_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        body.add(servers_frame, weight=2)
        self._bind_range_selection(self._servers_tree)
        self._bind_copy_json(self._servers_tree, lambda: self._servers_row_data)

        log_frame = ttk.LabelFrame(self, text="Activity log")
        log_frame.pack(side=tk.BOTTOM, fill=tk.BOTH, expand=False, padx=10, pady=(0, 10))
        self._log_text = tk.Text(log_frame, height=12, font=self._mono_font, state=tk.DISABLED, wrap=tk.NONE)
        log_scroll = ttk.Scrollbar(log_frame, orient=tk.VERTICAL, command=self._log_text.yview)
        self._log_text.configure(yscrollcommand=log_scroll.set)
        self._log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        log_scroll.pack(side=tk.RIGHT, fill=tk.Y)

    # -- update loop -----------------------------------------------------------

    def _drain_queue(self) -> None:
        latest_snapshot: Snapshot | None = None
        pending_events: list[Event] = []

        try:
            while True:
                snapshot, events = self._queue.get_nowait()
                latest_snapshot = snapshot
                pending_events.extend(events)
        except queue.Empty:
            pass

        if latest_snapshot is not None:
            self._render_snapshot(latest_snapshot)
        if pending_events:
            self._append_events(pending_events)

        self.after(DRAIN_INTERVAL_MS, self._drain_queue)

    def _render_snapshot(self, snapshot: Snapshot) -> None:
        if not snapshot.connected:
            self._status_var.set(f"⚠ disconnected from {snapshot.redis_uri}: {snapshot.error}")
            self._stats_var.set("")
            return

        self._status_var.set(f"● connected to {snapshot.redis_uri}")
        self._stats_var.set(
            f"redis {snapshot.redis_version}  |  clients {snapshot.connected_clients}  |  "
            f"memory {snapshot.used_memory_human}  |  awaiting delivery {snapshot.inflight_responses}"
        )

        self._render_methods(snapshot)
        self._render_servers(snapshot)

    # -- Shift-Up/Down range selection ----------------------------------------
    #
    # ttk.Treeview only wires up Shift-click for range selection (see
    # ttk::treeview::select.extend.extended in Tk's own treeview.tcl); there's
    # no keyboard equivalent, so arrow-key navigation never extends the
    # selection. This reimplements it using the same Tcl helper procs Tk uses
    # internally for mouse range-select (Keynav to move focus respecting
    # open/closed nodes, between() to compute the resulting flat range).

    def _bind_range_selection(self, tree: ttk.Treeview) -> None:
        tree.bind("<Shift-Down>", lambda e, t=tree: self._extend_selection(t, "down"))
        tree.bind("<Shift-Up>", lambda e, t=tree: self._extend_selection(t, "up"))
        # Plain arrow navigation only moves focus in stock ttk.Treeview,
        # leaving any prior multi-selection dangling -- collapse it to the
        # newly focused row so a later Shift-arrow starts from a clean anchor.
        tree.bind("<Down>", lambda e, t=tree: t.after_idle(self._collapse_selection_to_focus, t), add="+")
        tree.bind("<Up>", lambda e, t=tree: t.after_idle(self._collapse_selection_to_focus, t), add="+")

    @staticmethod
    def _collapse_selection_to_focus(tree: ttk.Treeview) -> None:
        focus = tree.focus()
        if focus:
            tree.selection_set(focus)

    def _extend_selection(self, tree: ttk.Treeview, direction: str) -> str:
        if len(tree.selection()) <= 1:
            self._select_anchor[tree] = tree.focus()
        anchor = self._select_anchor.get(tree) or tree.focus()
        if not anchor or not tree.exists(anchor):
            return "break"

        tree.tk.call("ttk::treeview::Keynav", str(tree), direction)
        new_focus = tree.focus()
        if new_focus:
            tree.selection_set(tree.tk.call("ttk::treeview::between", str(tree), anchor, new_focus))
            tree.see(new_focus)
        return "break"

    # -- Ctrl-C copy-as-JSON --------------------------------------------------

    def _bind_copy_json(self, tree: ttk.Treeview, get_row_data: Callable[[], dict[str, object]]) -> None:
        tree.bind("<Control-c>", lambda e, t=tree, g=get_row_data: self._copy_selection_as_json(t, g()))

    @staticmethod
    def _has_selected_ancestor(tree: ttk.Treeview, iid: str, selected: set[str]) -> bool:
        parent = tree.parent(iid)
        while parent:
            if parent in selected:
                return True
            parent = tree.parent(parent)
        return False

    def _copy_selection_as_json(self, tree: ttk.Treeview, row_data: dict[str, object]) -> str:
        # A selected group already nests its consumers (same for a selected
        # method nesting its groups), so if both are selected together, drop
        # the descendant -- otherwise its data shows up twice in the output.
        selected = set(tree.selection())
        top_level = [iid for iid in tree.selection() if not self._has_selected_ancestor(tree, iid, selected)]
        items = [row_data[iid] for iid in top_level if iid in row_data]
        if not items:
            return "break"

        payload = items[0] if len(items) == 1 else items
        tree.clipboard_clear()
        tree.clipboard_append(json.dumps(payload, indent=2, ensure_ascii=False))

        original_title = self.title()
        self.title(f"AnyCall Visualizer — copied {len(items)} row(s) as JSON")
        self.after(1500, lambda: self.title(original_title))
        return "break"

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

    @classmethod
    def _collect_open_iids(cls, tree: ttk.Treeview, parent: str = "") -> set[str]:
        """Open/closed state at every depth, not just top-level -- a plain
        rebuild resets every node to closed since ttk.Treeview.insert()
        defaults to open=False."""
        open_iids = set()
        for iid in tree.get_children(parent):
            if tree.item(iid, "open"):
                open_iids.add(iid)
            open_iids |= cls._collect_open_iids(tree, iid)
        return open_iids

    @staticmethod
    def _capture_tree_state(tree: ttk.Treeview) -> tuple[set[str], str]:
        return set(tree.selection()), tree.focus()

    @staticmethod
    def _restore_tree_state(tree: ttk.Treeview, selected: set[str], focused: str) -> None:
        still_there = [iid for iid in selected if tree.exists(iid)]
        if still_there:
            tree.selection_set(still_there)
        if focused and tree.exists(focused):
            tree.focus(focused)

    def _render_methods(self, snapshot: Snapshot) -> None:
        open_iids = self._collect_open_iids(self._methods_tree)
        selected, focused = self._capture_tree_state(self._methods_tree)
        self._methods_tree.delete(*self._methods_tree.get_children(""))
        self._methods_row_data.clear()

        for method in snapshot.methods:
            method_iid = f"method:{method.name}"
            self._methods_row_data[method_iid] = self._method_to_dict(method)
            self._methods_tree.insert(
                "",
                tk.END,
                iid=method_iid,
                text=method.name,
                values=(method.backlog, method.processing, method.consumer_count),
                open=method_iid in open_iids,
            )
            for group in method.groups:
                group_iid = f"{method_iid}:group:{group.name}"
                self._methods_row_data[group_iid] = self._group_to_dict(group, method.name)
                self._methods_tree.insert(
                    method_iid,
                    tk.END,
                    iid=group_iid,
                    text=f"group: {group.name}",
                    values=("", group.pending, len(group.consumers)),
                    open=group_iid in open_iids,
                )
                for consumer in group.consumers:
                    consumer_iid = f"{group_iid}:consumer:{consumer.name}"
                    self._methods_row_data[consumer_iid] = self._consumer_to_dict(consumer, method.name, group.name)
                    self._methods_tree.insert(
                        group_iid,
                        tk.END,
                        iid=consumer_iid,
                        text=f"consumer: {consumer.name}  (idle {consumer.idle_ms} ms)",
                        values=("", consumer.pending, ""),
                    )

        self._restore_tree_state(self._methods_tree, selected, focused)

    def _render_servers(self, snapshot: Snapshot) -> None:
        now = time.time()
        selected, focused = self._capture_tree_state(self._servers_tree)
        self._servers_tree.delete(*self._servers_tree.get_children(""))
        self._servers_row_data.clear()
        for server in snapshot.servers:
            self._servers_row_data[server.key] = self._server_to_dict(server)
            self._servers_tree.insert(
                "",
                tk.END,
                iid=server.key,
                text=server.server_id,
                values=(_age(server.last_heartbeat_epoch, now), f"{server.ttl_seconds}s"),
            )
        self._restore_tree_state(self._servers_tree, selected, focused)

    def _append_events(self, events: list[Event]) -> None:
        self._log_text.configure(state=tk.NORMAL)
        for event in events:
            ts = time.strftime("%H:%M:%S", time.localtime(event.timestamp))
            self._log_text.insert(tk.END, f"[{ts}] {event.message}\n")

        line_count = int(self._log_text.index("end-1c").split(".")[0])
        if line_count > MAX_LOG_LINES:
            self._log_text.delete("1.0", f"{line_count - MAX_LOG_LINES}.0")

        self._log_text.see(tk.END)
        self._log_text.configure(state=tk.DISABLED)

    def _on_font_size_change(self, *_args) -> None:
        try:
            size = int(self._font_size_var.get())
        except (tk.TclError, ValueError):
            return
        self._apply_font_size(size)

    def _apply_font_size(self, size: int) -> None:
        size = max(MIN_FONT_SIZE, min(MAX_FONT_SIZE, size))
        if size != self._font_size_var.get():
            self._font_size_var.set(size)

        for font in self._named_fonts.values():
            font.configure(size=size)
        self._bold_font.configure(size=size)
        self._mono_font.configure(size=size)

        default_font = self._named_fonts["TkDefaultFont"]
        self._style.configure("Treeview", rowheight=default_font.metrics("linespace") + 8)
        self._style.configure("Treeview", indent=round(TREE_BASE_INDENT * size / DEFAULT_FONT_SIZE))

        scale = size / DEFAULT_FONT_SIZE
        for tree, base_columns in (
            (self._methods_tree, METHODS_TREE_BASE_COLUMNS),
            (self._servers_tree, SERVERS_TREE_BASE_COLUMNS),
        ):
            for column, base_width in base_columns.items():
                tree.column(column, width=round(base_width * scale))

    def _on_close(self) -> None:
        self._poller.stop()
        self.destroy()
