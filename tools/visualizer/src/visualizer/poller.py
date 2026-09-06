"""Read-only collection of AnyCall protocol state from Redis.

Request/response queues can be either a Redis List (Java, as of the
Streams-to-Lists migration) or a Redis Stream (Python, still pending that
migration) -- this module checks each key's TYPE at poll time and issues the
right read-only commands for it, so both kinds show up side by side.

Live servers come from the same sorted set the servers heartbeat into
(`anycall:servers:alive`), read back the same way a server would prune it:
members scored within HEARTBEAT_TTL_SECONDS of now are alive, older ones are
dead but not yet swept.

Only ever issues non-destructive commands (SCAN, TYPE, LLEN, LRANGE, XLEN,
XRANGE, ZRANGEBYSCORE, INFO) -- never BRPOP/LPUSH/XREADGROUP/XACK/XDEL/ZADD/
ZREM/ZREMRANGEBYSCORE/CONFIG SET. This process must never be able to steal or
alter real RPC traffic; it only observes it.
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
from anycall.server import HEARTBEAT_KEY, HEARTBEAT_TTL_SECONDS
from PyQt6.QtCore import QThread, pyqtSignal

RESPONSE_QUEUE_PATTERN = f"{anycall_queues.RESPONSE_QUEUE_PREFIX}*"
REQUEST_QUEUE_PATTERN = f"{anycall_queues.REQUEST_QUEUE_PREFIX}*"
ENTRY_PEEK_COUNT = 20
PREVIEW_MAX_LEN = 60


@dataclass
class MethodInfo:
    name: str
    backlog: int
    kind: str = "stream"  # "list" (Java) or "stream" (Python), from the key's TYPE
    entries: dict[str, str] = field(default_factory=dict)  # entry id -> preview


@dataclass
class ServerInfo:
    server_id: str
    last_heartbeat: float  # epoch seconds, as recorded by the server itself
    age: float  # seconds since that heartbeat, by this process's clock


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


def _preview_request(raw_json: Optional[str | bytes]) -> str:
    if not raw_json:
        return "<malformed entry: missing data field>"
    if isinstance(raw_json, bytes):
        raw_json = raw_json.decode("utf-8", errors="replace")
    try:
        request = AnyCallRequest.from_dict(json.loads(raw_json))
    except Exception:
        return raw_json[:PREVIEW_MAX_LEN]
    payload = request.payload
    if len(payload) > PREVIEW_MAX_LEN:
        payload = payload[: PREVIEW_MAX_LEN - 3] + "..."
    return f"request_id={request.request_id} payload={payload}"


def _entry_key(raw_json: str | bytes) -> str:
    """Stable-ish key for diffing entries across polls. Prefers the request's
    own request_id (meaningful, and shared with its response key); falls
    back to a content hash if the entry doesn't parse. Never a List index --
    that shifts every time something is pushed or popped."""
    if isinstance(raw_json, bytes):
        raw_json = raw_json.decode("utf-8", errors="replace")
    try:
        request = AnyCallRequest.from_dict(json.loads(raw_json))
        return request.request_id
    except Exception:
        return f"content:{hash(raw_json)}"


def _method_name(queue_key: str) -> str:
    return queue_key[len(anycall_queues.REQUEST_QUEUE_PREFIX):]


def _collect_method(client: redis.Redis, queue_key: str) -> Optional[MethodInfo]:
    if not client.exists(queue_key):
        # Gone between the SCAN that found it and this call -- don't
        # fabricate a row for a queue that no longer exists in Redis.
        return None

    name = _method_name(queue_key)
    key_type = client.type(queue_key)

    if key_type == "list":
        return _collect_list_method(client, queue_key, name)
    if key_type == "stream":
        return _collect_stream_method(client, queue_key, name)
    return None


def _collect_list_method(client: redis.Redis, queue_key: str, name: str) -> MethodInfo:
    backlog = client.llen(queue_key)
    # LPUSH pushes to the head (index 0); BRPOP pops from the tail, so the
    # tail-most elements are next to be processed. Fetch the last N and
    # reverse them so index 0 of the preview is "next up" -- matching the
    # Stream path's oldest-first convention below.
    raw_entries = list(reversed(client.lrange(queue_key, -ENTRY_PEEK_COUNT, -1) or []))
    entries = {_entry_key(raw): _preview_request(raw) for raw in raw_entries}
    return MethodInfo(name=name, backlog=backlog, kind="list", entries=entries)


def _collect_stream_method(client: redis.Redis, queue_key: str, name: str) -> MethodInfo:
    backlog = client.xlen(queue_key)

    entries = {}
    for entry_id, fields in client.xrange(queue_key, count=ENTRY_PEEK_COUNT) or []:
        entries[entry_id] = _preview_request((fields or {}).get("data"))

    return MethodInfo(name=name, backlog=backlog, kind="stream", entries=entries)


def _collect_servers(client: redis.Redis, now: float) -> list[ServerInfo]:
    """Live servers, from the sorted set each server ZADDs itself into every
    HEARTBEAT_PERIOD_SECONDS. Members scored older than HEARTBEAT_TTL_SECONDS
    are servers that stopped refreshing their entry; they're filtered out here
    the same way a live server's next tick would prune them away.

    Scores are epoch seconds off the *server's* clock, so `age` is only as
    good as the clock agreement between that host and this one.
    """
    members = client.zrangebyscore(
        HEARTBEAT_KEY, now - HEARTBEAT_TTL_SECONDS, "+inf", withscores=True
    )
    servers = [
        ServerInfo(server_id=member, last_heartbeat=score, age=max(0.0, now - score))
        for member, score in members or []
    ]
    # ZRANGEBYSCORE hands them back oldest-heartbeat-first, which reshuffles
    # rows on every tick; sort by id so a server keeps its place in the table.
    servers.sort(key=lambda server: server.server_id)
    return servers


def collect_snapshot(client: redis.Redis, redis_uri: str) -> Snapshot:
    info = client.info()

    methods = [
        method
        for method in (
            _collect_method(client, queue_key)
            for queue_key in sorted(client.scan_iter(match=REQUEST_QUEUE_PATTERN, count=200))
        )
        if method is not None
    ]
    inflight_responses = sum(1 for _ in client.scan_iter(match=RESPONSE_QUEUE_PATTERN, count=200))

    taken_at = time.time()
    servers = _collect_servers(client, taken_at)

    return Snapshot(
        connected=True,
        taken_at=taken_at,
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
    flavor, not a complete audit log. The backlog gauge in Snapshot stays
    exact regardless.
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

        # Only against another connected snapshot: a poll that failed reports no
        # servers, which says nothing about whether they're still up.
        prev_connected = prev is not None and prev.connected
        if snapshot.connected:
            prev_servers = {s.server_id for s in prev.servers} if prev_connected else set()
            current_servers = {s.server_id for s in snapshot.servers}
            for server_id in sorted(current_servers - prev_servers):
                events.append(Event(now, f"server up: {server_id}"))
            # Servers never deregister themselves, so this covers every way one
            # can go away -- a clean stop and a crash both just stop refreshing
            # the entry, and there's nothing here to tell the two apart.
            for server_id in sorted(prev_servers - current_servers):
                events.append(Event(now, f"server gone: {server_id}"))

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
