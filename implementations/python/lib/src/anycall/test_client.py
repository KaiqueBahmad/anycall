"""Unit tests for AnyCallClient call/raw_call/register_type semantics."""

import json
from dataclasses import dataclass
from datetime import timedelta
from typing import List, Optional, Tuple

import pytest

from . import client as client_module
from .client import AnyCallClientImpl
from .config import AnycallProperties
from .exceptions import AnyCallError, QueueFullError, ServerLostError, TimeoutError
from .model import AnyCallRequest

pytestmark = pytest.mark.unit


@dataclass
class MockResponse:
    """Test model for deserialization."""
    value: str


@dataclass
class AlternativeResponse:
    """Alternative test model."""
    count: int


class MockRedisAdapter:
    """Mock Redis adapter for testing (returns None timeout immediately)."""

    def __init__(self, queue_depth: int = 0):
        self.queue_depth = queue_depth

    def push_and_wake(self, queue_key: str, value: str, channel: str) -> None:
        pass

    def pop(self, queue_keys: List[str], timeout_seconds: float) -> Optional[Tuple[str, str]]:
        return None

    def delete(self, key: str) -> int:
        return 0

    def length(self, queue_key: str) -> int:
        return self.queue_depth

    def alive_count(self, key: str, ttl_seconds: int) -> int:
        return 1

    def alive_members(self, key: str, ttl_seconds: int) -> set[str]:
        return {"live-server"}

    def inflight_owners(self, inflight_key: str) -> dict[str, str]:
        return {}

    def release_inflight(self, inflight_key: str, request_id: str) -> bool:
        return False

    def respond(self, response_queue: str, value: str, ttl_seconds: int, inflight_key: str = "", request_id: str = "") -> None:
        pass

    def close(self) -> None:
        pass


class DeadServerAdapter(MockRedisAdapter):
    """Every request pushed is taken by a server that is already dead, and
    nothing else is around to reap it."""

    def __init__(self):
        super().__init__()
        self.inflight: dict[str, str] = {}
        self.responses: dict[str, list[str]] = {}
        self.reaps = 0

    def push_and_wake(self, queue_key: str, value: str, channel: str) -> None:
        self.inflight[AnyCallRequest.from_dict(json.loads(value)).request_id] = "dead-server"

    def pop(self, queue_keys: List[str], timeout_seconds: float) -> Optional[Tuple[str, str]]:
        pending = self.responses.get(queue_keys[0])
        return (queue_keys[0], pending.pop()) if pending else None

    def inflight_owners(self, inflight_key: str) -> dict[str, str]:
        self.reaps += 1
        return dict(self.inflight)

    def release_inflight(self, inflight_key: str, request_id: str) -> bool:
        return self.inflight.pop(request_id, None) is not None

    def respond(self, response_queue: str, value: str, ttl_seconds: int, inflight_key: str = "", request_id: str = "") -> None:
        self.responses.setdefault(response_queue, []).insert(0, value)


def quick_props() -> AnycallProperties:
    # The mock's pop returns at once, so with no limit a call would spin forever.
    return AnycallProperties(timeout=timedelta(milliseconds=50))


@pytest.fixture
def client():
    """Create a test client with mock Redis adapter."""
    adapter = MockRedisAdapter()
    return AnyCallClientImpl(adapter, quick_props())


class TestRegisterType:
    """Tests for register_type() registry semantics."""

    def test_register_type_first_time(self, client):
        """First registration succeeds."""
        client.register_type("my-op", MockResponse)
        assert client._registry.has("my-op")
        assert client._registry.get("my-op") is MockResponse

    def test_register_type_same_type_idempotent(self, client):
        """Re-registering same type is idempotent (no error)."""
        client.register_type("my-op", MockResponse)
        client.register_type("my-op", MockResponse)  # Should not raise
        assert client._registry.get("my-op") is MockResponse

    def test_register_type_different_type_error(self, client):
        """Re-registering with different type raises error."""
        client.register_type("my-op", MockResponse)

        with pytest.raises(AnyCallError) as exc_info:
            client.register_type("my-op", AlternativeResponse)

        error_msg = str(exc_info.value)
        assert "my-op" in error_msg
        assert "already registered" in error_msg
        assert "MockResponse" in error_msg
        assert "AlternativeResponse" in error_msg

    def test_register_multiple_operations(self, client):
        """Different operations can be registered independently."""
        client.register_type("op1", MockResponse)
        client.register_type("op2", AlternativeResponse)

        assert client._registry.get("op1") is MockResponse
        assert client._registry.get("op2") is AlternativeResponse


class TestCallWithRegistry:
    """Tests for call() with registry lookup."""

    def test_call_without_type_not_registered_error(self, client):
        """Calling without type and without registry entry raises clear error."""
        with pytest.raises(AnyCallError) as exc_info:
            client.call("unknown-op", {})

        error_msg = str(exc_info.value)
        assert "unknown-op" in error_msg
        assert "register" in error_msg.lower() or "explicit type" in error_msg
        # Should suggest both paths
        assert "register_type" in error_msg or "explicit type" in error_msg

    def test_call_without_type_registered_uses_registry(self, client):
        """Calling without type uses registry when available."""
        client.register_type("my-op", MockResponse)

        # Note: This will timeout (mock adapter returns None), but that's OK
        # We're testing the registry lookup, not the full RPC
        with pytest.raises(AnyCallError) as exc_info:
            client.call("my-op", {})

        # Should fail with timeout, not "type not found"
        error_msg = str(exc_info.value)
        assert "Timeout" in error_msg or "timeout" in error_msg

    def test_call_with_explicit_type_ignores_registry(self, client):
        """Explicit type takes precedence over registry."""
        client.register_type("my-op", MockResponse)

        # Pass different type explicitly
        with pytest.raises(AnyCallError) as exc_info:
            client.call("my-op", {}, AlternativeResponse)

        # Should fail with timeout, not type mismatch
        error_msg = str(exc_info.value)
        assert "Timeout" in error_msg or "timeout" in error_msg


class TestRawCall:
    """Tests for raw_call() semantics."""

    def test_raw_call_ignores_registry(self, client):
        """raw_call() never uses registry."""
        # Register a type
        client.register_type("my-op", MockResponse)

        # raw_call should still work (timeout) without caring about type
        with pytest.raises(AnyCallError) as exc_info:
            client.raw_call("my-op", {})

        error_msg = str(exc_info.value)
        assert "Timeout" in error_msg or "timeout" in error_msg

    def test_raw_call_no_registry_needed(self, client):
        """raw_call() works without any registry entry."""
        # Don't register anything
        with pytest.raises(AnyCallError) as exc_info:
            client.raw_call("unregistered-op", {})

        # Should fail with timeout, not type lookup error
        error_msg = str(exc_info.value)
        assert "Timeout" in error_msg or "timeout" in error_msg


class TestErrorMessages:
    """Tests for error message quality."""

    def test_missing_type_error_suggests_both_paths(self, client):
        """Missing type error suggests both solutions."""
        with pytest.raises(AnyCallError) as exc_info:
            client.call("my-operation", {})

        error_msg = str(exc_info.value)
        # Should mention the operation name
        assert "my-operation" in error_msg
        # Should suggest both paths: explicit type and registry
        assert "explicit type" in error_msg.lower() or "call" in error_msg
        assert "register_type" in error_msg or "register" in error_msg.lower()

    def test_duplicate_type_error_names_types(self, client):
        """Duplicate type error names both the registered and attempted type."""
        client.register_type("operation", MockResponse)

        with pytest.raises(AnyCallError) as exc_info:
            client.register_type("operation", AlternativeResponse)

        error_msg = str(exc_info.value)
        # Should name both types
        assert "MockResponse" in error_msg
        assert "AlternativeResponse" in error_msg
        # Should mention the operation
        assert "operation" in error_msg


class TestQueueDepth:
    """Tests for max_queue_depth / QueueFullError semantics."""

    def test_call_raises_when_queue_at_max_depth(self):
        """Call is rejected before publishing when depth >= max_queue_depth."""
        adapter = MockRedisAdapter(queue_depth=5)
        client = AnyCallClientImpl(adapter, quick_props())

        with pytest.raises(QueueFullError) as exc_info:
            client.call("my-op", {}, MockResponse, max_queue_depth=5)

        assert exc_info.value.method_name == "my-op"
        assert exc_info.value.queue_depth == 5
        assert exc_info.value.max_queue_depth == 5

    def test_call_proceeds_when_queue_below_max_depth(self, client):
        """Call proceeds (and times out, since mock never responds) when depth is under the limit."""
        with pytest.raises(AnyCallError) as exc_info:
            client.call("my-op", {}, MockResponse, max_queue_depth=5)

        assert "Timeout" in str(exc_info.value)

    def test_default_max_queue_depth_applies_without_override(self):
        """Client-level default is used when no per-call override is given."""
        adapter = MockRedisAdapter(queue_depth=3)
        client = AnyCallClientImpl(adapter, quick_props(), default_max_queue_depth=3)

        with pytest.raises(QueueFullError):
            client.call("my-op", {}, MockResponse)

    def test_per_call_override_wins_over_default(self):
        """A per-call max_queue_depth overrides the client's default."""
        adapter = MockRedisAdapter(queue_depth=3)
        client = AnyCallClientImpl(adapter, quick_props(), default_max_queue_depth=1)

        with pytest.raises(AnyCallError) as exc_info:
            client.call("my-op", {}, MockResponse, max_queue_depth=10)

        assert "Timeout" in str(exc_info.value)

    def test_raw_call_respects_max_queue_depth(self):
        """raw_call() also enforces max_queue_depth."""
        adapter = MockRedisAdapter(queue_depth=2)
        client = AnyCallClientImpl(adapter, quick_props())

        with pytest.raises(QueueFullError):
            client.raw_call("my-op", {}, max_queue_depth=2)

    def test_no_max_queue_depth_is_unbounded(self, client):
        """No max_queue_depth set anywhere means the depth is never checked."""
        with pytest.raises(AnyCallError) as exc_info:
            client.call("my-op", {}, MockResponse)

        assert "Timeout" in str(exc_info.value)

    def test_get_queue_depth_reads_through_adapter(self):
        """get_queue_depth() reflects the adapter's stream length."""
        adapter = MockRedisAdapter(queue_depth=7)
        client = AnyCallClientImpl(adapter, quick_props())

        assert client.get_queue_depth("my-op") == 7

    def test_default_max_queue_depth_getter_and_setter(self, client):
        """set_default_max_queue_depth()/get_default_max_queue_depth() round-trip."""
        assert client.get_default_max_queue_depth() is None

        client.set_default_max_queue_depth(42)
        assert client.get_default_max_queue_depth() == 42

        client.set_default_max_queue_depth(None)
        assert client.get_default_max_queue_depth() is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


class TestWaiterDrivenReaping:
    """A waiting call reaps orphans itself once the client has gone quiet."""

    def test_call_reaps_its_dead_server_and_raises_server_lost(self, monkeypatch):
        monkeypatch.setattr(client_module, "WAITER_REAP_QUIET_SECONDS", 0)
        adapter = DeadServerAdapter()
        client = AnyCallClientImpl(adapter, AnycallProperties())

        with pytest.raises(ServerLostError) as exc_info:
            client.raw_call("my-op", {})

        assert exc_info.value.server_id == "dead-server"
        assert adapter.inflight == {}

    def test_no_reap_while_the_client_is_not_quiet(self):
        adapter = DeadServerAdapter()
        client = AnyCallClientImpl(adapter, quick_props())

        with pytest.raises(TimeoutError):
            client.raw_call("my-op", {})

        assert adapter.reaps == 0
        assert len(adapter.inflight) == 1

    def test_finding_a_live_server_before_publishing_resets_the_quiet_timer(self):
        adapter = DeadServerAdapter()
        client = AnyCallClientImpl(adapter, quick_props())
        client._last_activity = 0.0  # quiet for ages

        with pytest.raises(TimeoutError):
            client.raw_call("my-op", {})

        assert adapter.reaps == 0
