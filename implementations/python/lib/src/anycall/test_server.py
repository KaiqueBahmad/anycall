"""Unit tests for AnyCallServer: starting, and answering requests it can't parse."""

import json
import time
from typing import cast

import pytest

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

    def detect_blmove(self) -> bool:
        return True

    def heartbeat(self, key: str, member: str, ttl_seconds: int):
        if self.heartbeat_fails:
            raise ConnectionError("Redis is down")
        return True, set()

    def take(self, queue_key: str, processing_key: str, timeout_seconds: int):
        self.takes += 1
        time.sleep(0.01)
        return None

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
    server._process_request(server.method_handlers["echo"], item)


def test_request_with_unknown_field_is_answered_on_its_own_queue():
    adapter = FakeRedisAdapter()
    item = json.dumps({"requestId": "r1", "methodName": "echo", "payload": "{}", "extra": 1})

    process(adapter, item)

    response = adapter.responses["anycall:responses:r1"]
    assert response["payload"] is None
    assert response["error"]
    assert adapter.released == [item]


def test_request_missing_a_field_is_answered_on_its_own_queue():
    adapter = FakeRedisAdapter()
    item = json.dumps({"requestId": "r1", "methodName": "echo"})

    process(adapter, item)

    assert adapter.responses["anycall:responses:r1"]["error"]


@pytest.mark.parametrize("item", [
    "not json",
    json.dumps(["requestId", "r1"]),
    json.dumps({"methodName": "echo", "payload": "{}"}),
    json.dumps({"requestId": "", "methodName": "echo", "payload": "{}", "extra": 1}),
    json.dumps({"requestId": 7, "methodName": "echo", "payload": "{}", "extra": 1}),
])
def test_request_with_no_readable_request_id_is_dropped_unanswered(item):
    adapter = FakeRedisAdapter()

    process(adapter, item)

    assert adapter.responses == {}
    assert adapter.released == [item]
