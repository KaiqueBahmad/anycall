"""Read-only collection of AnyCall protocol state from Redis.

Only ever issues non-destructive commands (SCAN, XLEN, XRANGE, XINFO, GET,
TTL, INFO) -- never XREADGROUP/XACK/XDEL/CONFIG SET. This process must never
be able to steal or alter real RPC traffic; it only observes it.
"""
from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from typing import Optional

import redis
import redis.exceptions
from anycall import queues as anycall_queues
from anycall.model import AnyCallRequest
from PyQt6.QtCore import QThread, pyqtSignal

HEARTBEAT_PATTERN = "anycall:heartbeat:*"
RESPONSE_STREAM_PATTERN = f"{anycall_queues.RESPONSE_QUEUE_PREFIX}*"
REQUEST_STREAM_PATTERN = f"{anycall_queues.REQUEST_QUEUE_PREFIX}*"
ENTRY_PEEK_COUNT = 20
PREVIEW_MAX_LEN = 60


@dataclass
class ConsumerInfo:
    name: str
    pending: int
    idle_ms: int


@dataclass
class GroupInfo:
    name: str
    pending: int
    consumers: list[ConsumerInfo] = field(default_factory=list)


@dataclass
class MethodInfo:
    name: str
    backlog: int
    groups: list[GroupInfo] = field(default_factory=list)
    entries: dict[str, str] = field(default_factory=dict)  # entry id -> preview

    @property
    def processing(self) -> int:
        return sum(g.pending for g in self.groups)

    @property
    def consumer_count(self) -> int:
        return sum(len(g.consumers) for g in self.groups)


@dataclass
class ServerInfo:
    key: str
    server_id: str
    last_heartbeat_epoch: int
    ttl_seconds: int


@dataclass
class Snapshot:
    connected: bool
    taken_at: float
    redis_uri: str
    methods: list[MethodInfo] = field(default_factory=list)
    servers: list[ServerInfo] = field(default_factory=list)
    inflight_responses: int = 0
    redis_version: str = ""
    connected_clients: int = 0
    used_memory_human: str = ""
    error: Optional[str] = None


@dataclass
class Event:
    timestamp: float
    message: str


def _preview_request(raw_fields: dict) -> str:
    raw = raw_fields.get("data")
    if not raw:
        return "<malformed entry: missing data field>"
    try:
        request = AnyCallRequest.from_dict(json.loads(raw))
    except Exception:
        return raw[:PREVIEW_MAX_LEN]
    payload = request.payload
    if len(payload) > PREVIEW_MAX_LEN:
        payload = payload[: PREVIEW_MAX_LEN - 3] + "..."
    return f"request_id={request.request_id} payload={payload}"


def _method_name(stream_key: str) -> str:
    return stream_key[len(anycall_queues.REQUEST_QUEUE_PREFIX):]


def _collect_method(client: redis.Redis, stream_key: str) -> Optional[MethodInfo]:
    if not client.exists(stream_key):
        # Gone between the SCAN that found it and this call -- don't
        # fabricate a row for a stream that no longer exists in Redis.
        return None

    name = _method_name(stream_key)
    backlog = client.xlen(stream_key)

    groups: list[GroupInfo] = []
    try:
        for g in client.xinfo_groups(stream_key):
            group_name = g.get("name", "")
            consumers: list[ConsumerInfo] = []
            try:
                for c in client.xinfo_consumers(stream_key, group_name):
                    consumers.append(
                        ConsumerInfo(
                            name=c.get("name", ""),
                            pending=c.get("pending", 0),
                            idle_ms=c.get("idle", 0),
                        )
                    )
            except redis.ResponseError:
                pass
            groups.append(GroupInfo(name=group_name, pending=g.get("pending", 0), consumers=consumers))
    except redis.ResponseError:
        pass

    entries = {}
    for entry_id, fields in client.xrange(stream_key, count=ENTRY_PEEK_COUNT) or []:
        entries[entry_id] = _preview_request(fields or {})

    return MethodInfo(name=name, backlog=backlog, groups=groups, entries=entries)


def _collect_server(client: redis.Redis, key: str) -> Optional[ServerInfo]:
    value = client.get(key)
    if value is None:
        # Expired/deleted between the SCAN that found it and this GET --
        # it's not real Redis state anymore, so don't invent a row for it.
        return None
    ttl = client.ttl(key)
    if ttl == -2:
        # Same race, just caught on the TTL call instead of the GET.
        return None
    return ServerInfo(
        key=key,
        server_id=key.rsplit(":", 1)[-1],
        last_heartbeat_epoch=int(value) if value else 0,
        ttl_seconds=ttl if ttl and ttl > 0 else 0,
    )


def collect_snapshot(client: redis.Redis, redis_uri: str) -> Snapshot:
    info = client.info()

    methods = [
        method
        for method in (
            _collect_method(client, stream_key)
            for stream_key in sorted(client.scan_iter(match=REQUEST_STREAM_PATTERN, count=200))
        )
        if method is not None
    ]
    servers = [
        server
        for server in (
            _collect_server(client, key)
            for key in sorted(client.scan_iter(match=HEARTBEAT_PATTERN, count=200))
        )
        if server is not None
    ]
    inflight_responses = sum(1 for _ in client.scan_iter(match=RESPONSE_STREAM_PATTERN, count=200))

    return Snapshot(
        connected=True,
        taken_at=time.time(),
        redis_uri=redis_uri,
        methods=methods,
        servers=servers,
        inflight_responses=inflight_responses,
        redis_version=info.get("redis_version", "?"),
        connected_clients=info.get("connected_clients", 0),
        used_memory_human=info.get("used_memory_human", "?"),
    )


class ActivityTracker:
    """Diffs consecutive snapshots into human-readable events.

    Polling can't see everything -- a request that's queued and processed
    between two polls leaves no trace -- so this is best-effort activity
    flavor, not a complete audit log. The gauges in Snapshot (backlog,
    processing, consumers) stay exact regardless.
    """

    def __init__(self) -> None:
        self._prev: Optional[Snapshot] = None

    def diff(self, snapshot: Snapshot) -> list[Event]:
        events: list[Event] = []
        now = snapshot.taken_at
        prev = self._prev

        if prev is not None and prev.connected and not snapshot.connected:
            events.append(Event(now, f"lost connection to redis: {snapshot.error}"))
        elif prev is not None and not prev.connected and snapshot.connected:
            events.append(Event(now, "redis connection restored"))

        prev_methods = {m.name: m for m in prev.methods} if prev else {}
        for method in snapshot.methods:
            prev_method = prev_methods.get(method.name)
            if prev_method is None:
                events.append(Event(now, f"method discovered: {method.name}"))
            elif prev_method.backlog != method.backlog:
                events.append(
                    Event(now, f"{method.name}: backlog {prev_method.backlog} -> {method.backlog}")
                )

            prev_entries = prev_method.entries if prev_method else {}
            for entry_id, preview in method.entries.items():
                if entry_id not in prev_entries:
                    events.append(Event(now, f"{method.name}: request queued ({preview})"))

        prev_server_keys = {s.key for s in prev.servers} if prev else set()
        curr_server_keys = {s.key for s in snapshot.servers}
        for server in snapshot.servers:
            if server.key not in prev_server_keys:
                events.append(Event(now, f"server online: {server.server_id}"))
        for key in prev_server_keys - curr_server_keys:
            events.append(Event(now, f"server offline (heartbeat expired): {key.rsplit(':', 1)[-1]}"))

        self._prev = snapshot
        return events


class PollerThread(QThread):
    """Background thread that repeatedly collects a Snapshot and emits it
    (together with the events diffed since the previous poll) on the Qt
    event loop of whatever thread this object was created on."""

    snapshot_ready = pyqtSignal(object, object)  # Snapshot, list[Event]

    def __init__(self, redis_uri: str, interval: float = 1.0, parent=None):
        super().__init__(parent)
        self._redis_uri = redis_uri
        self._interval = interval
        self._stop_event = threading.Event()
        self._tracker = ActivityTracker()
        self._client: Optional[redis.Redis] = None

    def stop(self) -> None:
        self._stop_event.set()

    def run(self) -> None:
        while not self._stop_event.is_set():
            snapshot = self._poll_once()
            events = self._tracker.diff(snapshot)
            self.snapshot_ready.emit(snapshot, events)
            self._stop_event.wait(self._interval)

    def _poll_once(self) -> Snapshot:
        try:
            if self._client is None:
                self._client = redis.from_url(
                    self._redis_uri,
                    decode_responses=True,
                    socket_connect_timeout=2,
                    socket_timeout=2,
                )
            return collect_snapshot(self._client, self._redis_uri)
        except redis.exceptions.RedisError as e:
            self._client = None
            return Snapshot(connected=False, taken_at=time.time(), redis_uri=self._redis_uri, error=str(e))
