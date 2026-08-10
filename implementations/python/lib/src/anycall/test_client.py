"""Unit tests for AnyCallClient call/raw_call/register_type semantics."""

from dataclasses import dataclass
from typing import Dict

import pytest

from .client import AnyCallClientImpl
from .config import AnycallProperties
from .exceptions import AnyCallError, QueueFullError

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

    def add(self, stream_key: str, data: Dict[str, str]) -> str:
        return "fake-id"

    def read(self, stream_key: str, timeout_ms: int):
        return None

    def delete(self, key: str) -> int:
        return 0

    def length(self, stream_key: str) -> int:
        return self.queue_depth

    def close(self) -> None:
        pass


@pytest.fixture
def client():
    """Create a test client with mock Redis adapter."""
    adapter = MockRedisAdapter()
    props = AnycallProperties()
    return AnyCallClientImpl(adapter, props)


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
        client = AnyCallClientImpl(adapter, AnycallProperties())

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
        client = AnyCallClientImpl(adapter, AnycallProperties(), default_max_queue_depth=3)

        with pytest.raises(QueueFullError):
            client.call("my-op", {}, MockResponse)

    def test_per_call_override_wins_over_default(self):
        """A per-call max_queue_depth overrides the client's default."""
        adapter = MockRedisAdapter(queue_depth=3)
        client = AnyCallClientImpl(adapter, AnycallProperties(), default_max_queue_depth=1)

        with pytest.raises(AnyCallError) as exc_info:
            client.call("my-op", {}, MockResponse, max_queue_depth=10)

        assert "Timeout" in str(exc_info.value)

    def test_raw_call_respects_max_queue_depth(self):
        """raw_call() also enforces max_queue_depth."""
        adapter = MockRedisAdapter(queue_depth=2)
        client = AnyCallClientImpl(adapter, AnycallProperties())

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
        client = AnyCallClientImpl(adapter, AnycallProperties())

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
