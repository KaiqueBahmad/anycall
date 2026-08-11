"""Tkinter dashboard: renders Snapshots/Events produced by poller.PollerThread.

Purely observational -- no widget here ever triggers a Redis write.
"""
from __future__ import annotations

import queue
import time
import tkinter as tk
from tkinter import ttk

from .poller import Event, PollerThread, Snapshot

MAX_LOG_LINES = 1000
DRAIN_INTERVAL_MS = 150


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
        self.geometry("1080x680")

        self._queue: "queue.Queue" = queue.Queue()
        self._poller = PollerThread(redis_uri, self._queue, interval=interval)
        self._open_methods: set[str] = set()

        self._build_widgets(redis_uri)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        self._poller.start()
        self.after(DRAIN_INTERVAL_MS, self._drain_queue)

    # -- widget construction -------------------------------------------------

    def _build_widgets(self, redis_uri: str) -> None:
        header = ttk.Frame(self, padding=(10, 8))
        header.pack(side=tk.TOP, fill=tk.X)

        self._status_var = tk.StringVar(value=f"connecting to {redis_uri} ...")
        ttk.Label(header, textvariable=self._status_var, font=("TkDefaultFont", 10, "bold")).pack(side=tk.LEFT)

        self._stats_var = tk.StringVar(value="")
        ttk.Label(header, textvariable=self._stats_var).pack(side=tk.RIGHT)

        body = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        body.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=10, pady=(0, 8))

        methods_frame = ttk.LabelFrame(body, text="Methods (request streams)")
        self._methods_tree = ttk.Treeview(
            methods_frame,
            columns=("backlog", "processing", "consumers"),
            show="tree headings",
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

        servers_frame = ttk.LabelFrame(body, text="Servers (heartbeats)")
        self._servers_tree = ttk.Treeview(
            servers_frame,
            columns=("last_heartbeat", "ttl"),
            show="tree headings",
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

        log_frame = ttk.LabelFrame(self, text="Activity log")
        log_frame.pack(side=tk.BOTTOM, fill=tk.BOTH, expand=False, padx=10, pady=(0, 10))
        self._log_text = tk.Text(log_frame, height=12, font=("Courier", 10), state=tk.DISABLED, wrap=tk.NONE)
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

    def _render_methods(self, snapshot: Snapshot) -> None:
        self._open_methods = {
            iid for iid in self._methods_tree.get_children("") if self._methods_tree.item(iid, "open")
        }
        self._methods_tree.delete(*self._methods_tree.get_children(""))

        for method in snapshot.methods:
            method_iid = f"method:{method.name}"
            self._methods_tree.insert(
                "",
                tk.END,
                iid=method_iid,
                text=method.name,
                values=(method.backlog, method.processing, method.consumer_count),
                open=method_iid in self._open_methods,
            )
            for group in method.groups:
                group_iid = f"{method_iid}:group:{group.name}"
                self._methods_tree.insert(
                    method_iid,
                    tk.END,
                    iid=group_iid,
                    text=f"group: {group.name}",
                    values=("", group.pending, len(group.consumers)),
                )
                for consumer in group.consumers:
                    self._methods_tree.insert(
                        group_iid,
                        tk.END,
                        text=f"consumer: {consumer.name}  (idle {consumer.idle_ms} ms)",
                        values=("", consumer.pending, ""),
                    )

    def _render_servers(self, snapshot: Snapshot) -> None:
        now = time.time()
        self._servers_tree.delete(*self._servers_tree.get_children(""))
        for server in snapshot.servers:
            self._servers_tree.insert(
                "",
                tk.END,
                text=server.server_id,
                values=(_age(server.last_heartbeat_epoch, now), f"{server.ttl_seconds}s"),
            )

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

    def _on_close(self) -> None:
        self._poller.stop()
        self.destroy()
