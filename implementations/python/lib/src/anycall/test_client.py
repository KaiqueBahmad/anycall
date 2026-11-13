"""Unit tests for AnyCallClient call/raw_call/register_type semantics."""

from dataclasses import dataclass
from datetime import timedelta
from typing import List, Optional, Tuple

import pytest
import redis.exceptions

from . import client as client_module
from .client import AnyCallClientImpl
from .exceptions import (
    AnyCallError,
    BrokerError,
    QueueFullError,
    SerializationError,
    ServerLostError,
    TimeoutError,
)

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

    def push(self, queue_key: str, value: str) -> int:
        return 1

    def pop(self, queue_keys: List[str], timeout_seconds: float) -> Optional[Tuple[str, str]]:
        return None

    def delete(self, key: str) -> int:
        return 0

    def length(self, queue_key: str) -> int:
        return self.queue_depth

    def alive_count(self, key: str, ttl_seconds: int) -> int:
        return 1

    def stale_members(self, key: str, ttl_seconds: int) -> set[str]:
        return set()

    def fail_back_next(self, alive_key, processing_key, server_id, response_ttl_seconds, tombstone_ttl_seconds, response_for):
        return None

    def respond(self, response_queue: str, value: str, ttl_seconds: int, processing_key: str = "", item: str = "") -> None:
        pass

    def close(self) -> None:
        pass


class DeadServerAdapter(MockRedisAdapter):
    """Every request pushed is taken by a server that then stops
    heartbeating, and nothing else is around to reap it."""

    def __init__(self, dead: bool = True):
        super().__init__()
        self.dead = dead
        self.processing: dict[str, list[str]] = {"dead-server": []}
        self.responses: dict[str, list[str]] = {}
        self.reap_steps = 0

    def push(self, queue_key: str, value: str) -> int:
        self.processing["dead-server"].append(value)
        return 1

    def pop(self, queue_keys: List[str], timeout_seconds: float) -> Optional[Tuple[str, str]]:
        pending = self.responses.get(queue_keys[0])
        return (queue_keys[0], pending.pop()) if pending else None

    def stale_members(self, key: str, ttl_seconds: int) -> set[str]:
        return {server for server in self.processing if self.dead}

    def fail_back_next(self, alive_key, processing_key, server_id, response_ttl_seconds, tombstone_ttl_seconds, response_for):
        self.reap_steps += 1
        assert processing_key == f"anycall:processing:{server_id}"
        items = self.processing.get(server_id)
        if items is None:
            return None
        if not items:
            del self.processing[server_id]
            return None
        target = response_for(items.pop())
        if target is not None:
            self.respond(target[0], target[1], response_ttl_seconds)
        return "dropped" if target is None else "answered"

    def respond(self, response_queue: str, value: str, ttl_seconds: int, processing_key: str = "", item: str = "") -> None:
        self.responses.setdefault(response_queue, []).insert(0, value)


# The mock's pop returns at once, so with no limit a call would spin forever.
QUICK_TIMEOUT = timedelta(milliseconds=50)


@pytest.fixture
def client():
    """Create a test client with mock Redis adapter."""
    adapter = MockRedisAdapter()
    return AnyCallClientImpl(adapter, QUICK_TIMEOUT)


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
        client = AnyCallClientImpl(adapter, QUICK_TIMEOUT)

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
        client = AnyCallClientImpl(adapter, QUICK_TIMEOUT, default_max_queue_depth=3)

        with pytest.raises(QueueFullError):
            client.call("my-op", {}, MockResponse)

    def test_per_call_override_wins_over_default(self):
        """A per-call max_queue_depth overrides the client's default."""
        adapter = MockRedisAdapter(queue_depth=3)
        client = AnyCallClientImpl(adapter, QUICK_TIMEOUT, default_max_queue_depth=1)

        with pytest.raises(AnyCallError) as exc_info:
            client.call("my-op", {}, MockResponse, max_queue_depth=10)

        assert "Timeout" in str(exc_info.value)

    def test_raw_call_respects_max_queue_depth(self):
        """raw_call() also enforces max_queue_depth."""
        adapter = MockRedisAdapter(queue_depth=2)
        client = AnyCallClientImpl(adapter, QUICK_TIMEOUT)

        with pytest.raises(QueueFullError):
            client.raw_call("my-op", {}, max_queue_depth=2)

    def test_no_max_queue_depth_is_unbounded(self, client):
        """No max_queue_depth set anywhere means the depth is never checked."""
        with pytest.raises(AnyCallError) as exc_info:
            client.call("my-op", {}, MockResponse)

        assert "Timeout" in str(exc_info.value)

    def test_get_queue_depth_reads_through_adapter(self):
        """get_queue_depth() reflects the adapter's queue length."""
        adapter = MockRedisAdapter(queue_depth=7)
        client = AnyCallClientImpl(adapter, QUICK_TIMEOUT)

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
    """A call whose wait slice ends empty reaps dead servers itself."""

    def test_call_reaps_its_dead_server_and_raises_server_lost(self, monkeypatch):
        monkeypatch.setattr(client_module, "WAITER_REAP_SLICE_SECONDS", 0.01)
        adapter = DeadServerAdapter()
        client = AnyCallClientImpl(adapter)

        with pytest.raises(ServerLostError) as exc_info:
            client.raw_call("my-op", {})

        assert exc_info.value.server_id == "dead-server"
        assert "dead-server" not in adapter.processing

    def test_no_claim_while_every_server_is_alive(self):
        adapter = DeadServerAdapter(dead=False)
        client = AnyCallClientImpl(adapter, QUICK_TIMEOUT)

        with pytest.raises(TimeoutError):
            client.raw_call("my-op", {})

        assert adapter.reap_steps == 0
        assert len(adapter.processing["dead-server"]) == 1


class RespondingAdapter(MockRedisAdapter):
    """Answers every call with `response`."""

    def __init__(self, response: str):
        super().__init__()
        self.response = response

    def pop(self, queue_keys: List[str], timeout_seconds: float) -> Optional[Tuple[str, str]]:
        return queue_keys[0], self.response


class TestResponseFields:
    """Responses are read by their camelCase wire names only."""

    def test_camel_case_response_is_read(self):
        adapter = RespondingAdapter('{"requestId": "r1", "payload": "{\\"value\\": \\"ok\\"}", "error": null}')
        client = AnyCallClientImpl(adapter, QUICK_TIMEOUT)

        assert client.call("my-op", {}, MockResponse) == MockResponse(value="ok")

    def test_response_with_other_field_name_is_a_serialization_error(self):
        adapter = RespondingAdapter('{"requestId": "r1", "payload": null, "errorMsg": "boom"}')
        client = AnyCallClientImpl(adapter, QUICK_TIMEOUT)

        with pytest.raises(SerializationError):
            client.raw_call("my-op", {})


class TestNullPayload:
    """A null result travels as the payload "null"; a null payload is a broken response."""

    def test_null_result_is_none_for_typed_call(self):
        adapter = RespondingAdapter('{"requestId": "r1", "payload": "null", "error": null}')
        client = AnyCallClientImpl(adapter, QUICK_TIMEOUT)

        assert client.call("my-op", {}, MockResponse) is None

    def test_null_result_is_none_for_raw_call(self):
        adapter = RespondingAdapter('{"requestId": "r1", "payload": "null", "error": null}')
        client = AnyCallClientImpl(adapter, QUICK_TIMEOUT)

        assert client.raw_call("my-op", {}) is None

    def test_response_with_neither_payload_nor_error_is_a_serialization_error(self):
        adapter = RespondingAdapter('{"requestId": "r1", "payload": null, "error": null}')
        client = AnyCallClientImpl(adapter, QUICK_TIMEOUT)

        with pytest.raises(SerializationError, match="neither a payload nor an error"):
            client.call("my-op", {}, MockResponse)

    def test_payload_that_does_not_fit_the_type_is_a_serialization_error(self):
        adapter = RespondingAdapter('{"requestId": "r1", "payload": "{\\\\"other\\\\": 1}", "error": null}')
        client = AnyCallClientImpl(adapter, QUICK_TIMEOUT)

        with pytest.raises(SerializationError):
            client.call("my-op", {}, MockResponse)


class FailingRedisAdapter(MockRedisAdapter):
    """Raises a redis-py ConnectionError from the command named `fails`."""

    def __init__(self, fails: str):
        super().__init__()
        self.fails = fails
        self.pushed = False
        self.deleted = False

    def _maybe_fail(self, command: str) -> None:
        if command == self.fails:
            raise redis.exceptions.ConnectionError("Connection refused")

    def alive_count(self, key: str, ttl_seconds: int) -> int:
        self._maybe_fail("alive_count")
        return 1

    def length(self, queue_key: str) -> int:
        self._maybe_fail("length")
        return 0

    def push(self, queue_key: str, value: str) -> int:
        self._maybe_fail("push")
        self.pushed = True
        return 1

    def pop(self, queue_keys: List[str], timeout_seconds: float) -> Optional[Tuple[str, str]]:
        self._maybe_fail("pop")
        return None

    def delete(self, key: str) -> int:
        self.deleted = True
        return 0


class TestBrokerError:
    """A Redis failure during a call is a BrokerError saying whether the request may have left."""

    @pytest.mark.parametrize("fails", ["alive_count", "length"])
    def test_failure_before_publishing_is_not_published(self, fails):
        client = AnyCallClientImpl(FailingRedisAdapter(fails), QUICK_TIMEOUT, default_max_queue_depth=10)

        with pytest.raises(BrokerError) as exc_info:
            client.raw_call("my-op", {})

        assert exc_info.value.published is False
        assert isinstance(exc_info.value.__cause__, redis.exceptions.ConnectionError)

    @pytest.mark.parametrize("fails", ["push", "pop"])
    def test_failure_from_publishing_on_may_be_published(self, fails):
        client = AnyCallClientImpl(FailingRedisAdapter(fails), QUICK_TIMEOUT)

        with pytest.raises(BrokerError) as exc_info:
            client.raw_call("my-op", {})

        assert exc_info.value.published is True
        assert exc_info.value.get_id()

    def test_response_queue_is_not_deleted_after_a_redis_failure(self):
        adapter = FailingRedisAdapter("pop")
        client = AnyCallClientImpl(adapter, QUICK_TIMEOUT)

        with pytest.raises(BrokerError):
            client.raw_call("my-op", {})

        assert adapter.deleted is False


class TestInvalidJson:
    """Invalid JSON, in the response or its payload, is a plain SerializationError."""

    @pytest.mark.parametrize("response", [
        "not json",
        '{"requestId": "r1", "payload": "not json", "error": null}',
    ])
    def test_invalid_json_is_a_serialization_error(self, response):
        client = AnyCallClientImpl(RespondingAdapter(response), QUICK_TIMEOUT)

        with pytest.raises(SerializationError) as exc_info:
            client.raw_call("my-op", {})

        assert type(exc_info.value) is SerializationError
