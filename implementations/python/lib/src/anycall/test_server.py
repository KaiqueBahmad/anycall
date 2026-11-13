"""Unit tests for AnyCallServer: starting, and answering requests it can't parse."""

import json
import time
from typing import cast

import pytest
import redis.exceptions

from . import server as server_module
from .annotation import supply
from .context import AnycallContext
from .exceptions import AnyCallError
from .redis_adapter import RedisQueueAdapter
from .server import AnyCallServer, AnyCallServerImpl


class Echo:
    @supply("echo")
    def echo(self, ctx: AnycallContext, request: dict) -> dict:
        return request


class FakeRedisAdapter:
    """Records takes, responses and releases; its heartbeat fails while
    `heartbeat_fails` is set."""

    def __init__(self, heartbeat_fails: bool = False):
        self.heartbeat_fails = heartbeat_fails
        self.takes = 0
        self.responses: dict[str, dict] = {}
        self.released: list[str] = []
        self.heartbeats: list[tuple[str, bool]] = []
        self.declared_dead: set[str] = set()
        self.dead_servers: set[str] = set()
        self.reaped: list[str] = []
        self.dropped_tombstones: list[str] = []
        self.tombstoned: set[str] = set()

    def detect_blmove(self) -> bool:
        return True

    def heartbeat(self, key: str, member: str, ttl_seconds: int, first: bool):
        if self.heartbeat_fails:
            raise ConnectionError("Redis is down")
        self.heartbeats.append((member, first))
        if member in self.declared_dead:
            return None
        return set(self.dead_servers)

    def fail_back_next(self, alive_key, processing_key, server_id, response_ttl_seconds, tombstone_ttl_seconds, response_for):
        self.reaped.append(server_id)
        return None

    def take(self, queue_key: str, processing_key: str, timeout_seconds: int):
        self.takes += 1
        time.sleep(0.01)
        if processing_key in self.tombstoned:
            raise redis.exceptions.ResponseError("WRONGTYPE Operation against a key holding the wrong kind of value")
        return None

    def drop_tombstone(self, processing_key: str):
        self.dropped_tombstones.append(processing_key)

    def respond(self, response_queue: str, value: str, ttl_seconds: int, processing_key: str = "", item: str = ""):
        self.responses[response_queue] = json.loads(value)
        self.released.append(item)

    def release(self, processing_key: str, item: str):
        self.released.append(item)


def make_server(adapter: FakeRedisAdapter) -> AnyCallServer:
    return AnyCallServerImpl(cast(RedisQueueAdapter, adapter)).register(Echo())


@pytest.fixture(autouse=True)
def fast_heartbeat(monkeypatch):
    monkeypatch.setattr(server_module, "HEARTBEAT_PERIOD_SECONDS", 0.01)


def test_start_raises_and_takes_nothing_when_first_heartbeat_fails():
    adapter = FakeRedisAdapter(heartbeat_fails=True)
    server = make_server(adapter)

    with pytest.raises(AnyCallError, match="first heartbeat"):
        server.start()

    time.sleep(0.05)
    assert not server.is_running()
    assert adapter.takes == 0


def test_start_can_be_retried_after_first_heartbeat_fails():
    adapter = FakeRedisAdapter(heartbeat_fails=True)
    server = make_server(adapter)
    with pytest.raises(AnyCallError):
        server.start()

    adapter.heartbeat_fails = False
    server.start()
    try:
        assert server.is_running()
        deadline = time.monotonic() + 1
        while adapter.takes == 0 and time.monotonic() < deadline:
            time.sleep(0.01)
        assert adapter.takes > 0
    finally:
        server.stop()


def process(adapter: FakeRedisAdapter, item: str) -> None:
    server = AnyCallServerImpl(cast(RedisQueueAdapter, adapter))
    server.register(Echo())
    server._process_request(server.method_handlers["echo"], item, server._identity)


def test_request_with_unknown_field_is_answered_on_its_own_queue():
    adapter = FakeRedisAdapter()
    item = json.dumps({"requestId": "r1", "clientId": "c1", "methodName": "echo", "payload": "{}", "extra": 1})

    process(adapter, item)

    response = adapter.responses["anycall:responses:c1"]
    assert response["requestId"] == "r1"
    assert response["payload"] is None
    assert response["error"]
    assert adapter.released == [item]


def test_request_missing_a_field_is_answered_on_its_own_queue():
    adapter = FakeRedisAdapter()
    item = json.dumps({"requestId": "r1", "clientId": "c1", "methodName": "echo"})

    process(adapter, item)

    assert adapter.responses["anycall:responses:c1"]["error"]


@pytest.mark.parametrize("item", [
    "not json",
    json.dumps(["requestId", "r1"]),
    json.dumps({"methodName": "echo", "payload": "{}"}),
    json.dumps({"requestId": "", "methodName": "echo", "payload": "{}", "extra": 1}),
    json.dumps({"requestId": 7, "methodName": "echo", "payload": "{}", "extra": 1}),
    json.dumps({"requestId": "r1", "methodName": "echo", "payload": "{}", "extra": 1}),  # no clientId
])
def test_request_with_no_readable_request_id_is_dropped_unanswered(item):
    adapter = FakeRedisAdapter()

    process(adapter, item)

    assert adapter.responses == {}
    assert adapter.released == [item]


def test_a_server_declared_dead_carries_on_under_a_new_id():
    adapter = FakeRedisAdapter()
    server = AnyCallServerImpl(cast(RedisQueueAdapter, adapter))
    server._heartbeat()
    old_id = server.server_id
    assert adapter.heartbeats == [(old_id, True)]

    adapter.declared_dead.add(old_id)
    server._heartbeat()

    assert server.server_id != old_id
    # The old id is refused, then the new one heartbeats for the first time.
    assert adapter.heartbeats[1:] == [(old_id, False), (server.server_id, True)]


def test_results_of_requests_taken_under_a_draining_id_are_discarded():
    adapter = FakeRedisAdapter()
    server = AnyCallServerImpl(cast(RedisQueueAdapter, adapter))
    server.register(Echo())
    server._heartbeat()
    taker = server._identity
    adapter.declared_dead.add(taker.server_id)
    server._heartbeat()

    item = json.dumps({"requestId": "r1", "clientId": "c1", "methodName": "echo", "payload": "{}"})
    server._process_request(server.method_handlers["echo"], item, taker)

    assert adapter.responses == {}
    assert adapter.released == []


def test_a_draining_id_drops_its_tombstone_once_no_take_is_on_it():
    adapter = FakeRedisAdapter()
    server = AnyCallServerImpl(cast(RedisQueueAdapter, adapter))
    server._heartbeat()
    old = server._identity
    adapter.declared_dead.add(old.server_id)

    server._heartbeat()

    # Its list was reaped, then its tombstone dropped, in that order.
    assert adapter.reaped == [old.server_id]
    assert adapter.dropped_tombstones == [old.processing_key]


def test_a_draining_id_keeps_its_tombstone_while_a_take_is_on_it():
    adapter = FakeRedisAdapter()
    server = AnyCallServerImpl(cast(RedisQueueAdapter, adapter))
    server._heartbeat()
    old = server._identity
    old.active_takes = 1  # a read loop is blocked taking onto its list
    adapter.declared_dead.add(old.server_id)

    server._heartbeat()
    assert adapter.dropped_tombstones == []

    old.active_takes = 0  # the take returned
    server._heartbeat()
    assert adapter.dropped_tombstones == [old.processing_key]


def test_a_take_that_hits_its_tombstone_drains_at_once():
    adapter = FakeRedisAdapter()
    server = AnyCallServerImpl(cast(RedisQueueAdapter, adapter)).register(Echo())
    server.start()
    try:
        old_id = server.server_id
        adapter.tombstoned.add(server._identity.processing_key)
        deadline = time.monotonic() + 2
        while server.server_id == old_id and time.monotonic() < deadline:
            time.sleep(0.01)
        new_id = server.server_id
        assert new_id != old_id
        # The new id is registered by an early heartbeat, then taken under.
        while (new_id, True) not in adapter.heartbeats and time.monotonic() < deadline:
            time.sleep(0.01)
        assert (new_id, True) in adapter.heartbeats
    finally:
        server.stop()
