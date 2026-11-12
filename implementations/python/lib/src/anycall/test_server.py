"""Unit tests for AnyCallServer start."""

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
    """Records takes; its heartbeat fails while `heartbeat_fails` is set."""

    def __init__(self, heartbeat_fails: bool):
        self.heartbeat_fails = heartbeat_fails
        self.takes = 0

    def heartbeat(self, key: str, member: str, ttl_seconds: int):
        if self.heartbeat_fails:
            raise ConnectionError("Redis is down")
        return True, set()

    def take(self, queue_key: str, processing_key: str, timeout_seconds: int):
        self.takes += 1
        time.sleep(0.01)
        return None


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
