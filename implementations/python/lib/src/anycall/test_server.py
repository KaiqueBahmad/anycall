"""Unit tests for AnyCallServer: starting, and answering requests it can't parse."""

import json
import threading
import time
from typing import cast

import pytest
import redis.exceptions

from . import server as server_module
from .annotation import supply
from .context import AnycallContext
from .exceptions import AnyCallError
from .redis_adapter import RedisQueueAdapter
from .options import ServerOptions
from .queues import Queues
from .server import AnyCallServer, AnyCallServerImpl, MethodInfo, SupplyMethod


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
        self.closes = 0

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

    def close(self):
        self.closes += 1


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


def test_close_stops_the_server_and_closes_its_connections_once():
    adapter = FakeRedisAdapter()
    server = make_server(adapter)
    server.start()

    server.close()
    server.close()

    assert not server.is_running()
    assert adapter.closes == 1
    with pytest.raises(RuntimeError, match="closed"):
        server.start()


def test_a_server_closes_at_the_end_of_a_with_block():
    adapter = FakeRedisAdapter()
    with make_server(adapter) as server:
        server.start()
        assert server.is_running()

    assert not server.is_running()
    assert adapter.closes == 1


def test_a_server_never_started_closes_its_connections_too():
    adapter = FakeRedisAdapter()
    make_server(adapter).close()

    assert adapter.closes == 1


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


def test_server_takes_and_heartbeats_under_its_prefix():
    adapter = FakeRedisAdapter()
    keys: list[str] = []
    take = adapter.take
    adapter.take = lambda queue_key, processing_key, timeout: keys.append(queue_key) or take(queue_key, processing_key, timeout)
    heartbeat = adapter.heartbeat
    adapter.heartbeat = lambda key, member, ttl, first: keys.append(key) or heartbeat(key, member, ttl, first)
    server = AnyCallServerImpl(cast(RedisQueueAdapter, adapter), keys=Queues("billing")).register(Echo())
    server.start()
    try:
        deadline = time.monotonic() + 1
        while "billing:requests:echo" not in keys and time.monotonic() < deadline:
            time.sleep(0.01)
    finally:
        server.stop()

    assert "billing:servers:alive" in keys
    assert "billing:requests:echo" in keys
    assert server._identity.processing_key.startswith("billing:processing:")


def test_update_options_changes_only_what_it_sets():
    server = AnyCallServerImpl(cast(RedisQueueAdapter, FakeRedisAdapter()), ServerOptions(max_concurrency=4))

    server.update_options(ServerOptions())
    assert server.options.max_concurrency_or(0) == 4

    server.update_options(ServerOptions(max_concurrency=8))
    assert server.options.max_concurrency_or(0) == 8

    server.update_options(ServerOptions(max_concurrency=None))
    assert server.options.max_concurrency_or(0) is None


def test_raising_the_cap_lets_a_waiter_in():
    limiter = server_module.ConcurrencyLimiter(1)
    assert limiter.acquire(0)
    assert not limiter.acquire(0.05)

    limiter.set_capacity(2)

    assert limiter.acquire(0)


def test_lowering_the_cap_lets_running_ones_finish_first():
    limiter = server_module.ConcurrencyLimiter(3)
    assert limiter.acquire(0) and limiter.acquire(0)

    limiter.set_capacity(1)
    limiter.release()
    assert not limiter.acquire(0.05)
    limiter.release()

    assert limiter.acquire(0)


def test_no_cap_never_waits():
    limiter = server_module.ConcurrencyLimiter(None)

    assert all(limiter.acquire(0) for _ in range(1000))


class Slow:
    @supply("slow", max_concurrency=2)
    def slow(self, ctx: AnycallContext, request: dict) -> dict:
        return request


def test_methods_lists_every_registered_name():
    server = AnyCallServerImpl(cast(RedisQueueAdapter, FakeRedisAdapter())).register(Slow(), Echo())

    assert server.methods == ["echo", "slow"]

    server.unregister("echo")
    assert server.methods == ["slow"]


def test_method_reads_one_methods_cap_and_running_count():
    server = AnyCallServerImpl(cast(RedisQueueAdapter, FakeRedisAdapter())).register(Slow(), Echo())

    assert server.method("slow") == MethodInfo(2, 0, SupplyMethod("slow", 2, dict, dict))
    with pytest.raises(KeyError):
        server.method("missing")


def test_set_max_concurrency_changes_one_methods_cap():
    server = AnyCallServerImpl(cast(RedisQueueAdapter, FakeRedisAdapter())).register(Slow(), Echo())

    server.set_max_concurrency("slow", 5)

    assert server.method("slow").max_concurrency == 5
    assert server.method("slow").declared.max_concurrency == 2
    assert server.method("echo").max_concurrency == 1


def test_running_counts_requests_while_they_run():
    started, release = threading.Event(), threading.Event()

    class Blocking:
        @supply("block")
        def block(self, ctx: AnycallContext, request: dict) -> dict:
            started.set()
            release.wait(2)
            return request

    adapter = FakeRedisAdapter()
    server = AnyCallServerImpl(cast(RedisQueueAdapter, adapter)).register(Blocking())
    item = json.dumps({"requestId": "r1", "clientId": "c1", "methodName": "block", "payload": "{}"})
    server._method_limiters["block"].acquire(0)
    server._global_limiter.acquire(0)
    worker = threading.Thread(target=server._process_message, args=(
        item, server.method_handlers["block"], server._method_limiters["block"], server._identity,
        server._running_requests["block"]))
    worker.start()
    started.wait(2)

    assert server.method("block").running == 1
    release.set()
    worker.join(2)
    assert server.method("block").running == 0


def test_set_max_concurrency_rejects_bad_values_and_unknown_methods():
    server = AnyCallServerImpl(cast(RedisQueueAdapter, FakeRedisAdapter())).register(Echo())

    with pytest.raises(ValueError):
        server.set_max_concurrency("echo", 0)
    with pytest.raises(TypeError):
        server.set_max_concurrency("echo", True)
    with pytest.raises(KeyError):
        server.set_max_concurrency("missing", 3)


def test_a_function_registered_with_its_declaration_is_served():
    adapter = FakeRedisAdapter()
    server = AnyCallServerImpl(cast(RedisQueueAdapter, adapter))
    server.register_method(SupplyMethod("shout", 3, str, str), lambda ctx, text: text.upper())

    assert server.methods == ["shout"]
    assert server.method("shout") == MethodInfo(3, 0, SupplyMethod("shout", 3, str, str))

    item = json.dumps({"requestId": "r1", "clientId": "c1", "methodName": "shout", "payload": '"hi"'})
    server._process_request(server.method_handlers["shout"], item, server._identity)
    assert adapter.responses["anycall:responses:c1"]["payload"] == '"HI"'


def test_what_a_registered_function_raises_is_its_calls_error():
    adapter = FakeRedisAdapter()
    server = AnyCallServerImpl(cast(RedisQueueAdapter, adapter))

    def fails(ctx, request):
        raise ValueError("text is empty")

    server.register_method(SupplyMethod("shout", 1, str, str), fails)
    item = json.dumps({"requestId": "r1", "clientId": "c1", "methodName": "shout", "payload": '""'})
    server._process_request(server.method_handlers["shout"], item, server._identity)

    assert adapter.responses["anycall:responses:c1"]["error"] == "text is empty"


def test_register_method_rejects_a_bad_declaration_or_handler():
    server = AnyCallServerImpl(cast(RedisQueueAdapter, FakeRedisAdapter()))

    with pytest.raises(ValueError, match="needs a name"):
        server.register_method(SupplyMethod(" ", 1, str, str), lambda ctx, r: r)
    with pytest.raises(ValueError, match="at least 1"):
        server.register_method(SupplyMethod("x", 0, str, str), lambda ctx, r: r)
    with pytest.raises(TypeError, match="callable"):
        server.register_method(SupplyMethod("x", 1, str, str), "not a function")
    assert server.methods == []
