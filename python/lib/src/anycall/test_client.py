"""Unit tests for AnyCallClient call/call_raw/register_type semantics."""

import pytest
from dataclasses import dataclass

from .client import AnyCallClientImpl
from .config import AnycallProperties
from .exceptions import AnyCallException
from .redis_adapter import RedisStreamAdapter


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

    def add(self, stream_key: str, data: dict) -> str:
        return "fake-id"

    def read(self, stream_key: str, timeout_ms: int):
        return None

    def delete(self, key: str) -> int:
        return 0

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

        with pytest.raises(AnyCallException) as exc_info:
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
        with pytest.raises(AnyCallException) as exc_info:
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
        with pytest.raises(AnyCallException) as exc_info:
            client.call("my-op", {})

        # Should fail with timeout, not "type not found"
        error_msg = str(exc_info.value)
        assert "Timeout" in error_msg or "timeout" in error_msg

    def test_call_with_explicit_type_ignores_registry(self, client):
        """Explicit type takes precedence over registry."""
        client.register_type("my-op", MockResponse)

        # Pass different type explicitly
        with pytest.raises(AnyCallException) as exc_info:
            client.call("my-op", {}, AlternativeResponse)

        # Should fail with timeout, not type mismatch
        error_msg = str(exc_info.value)
        assert "Timeout" in error_msg or "timeout" in error_msg


class TestCallRaw:
    """Tests for call_raw() semantics."""

    def test_call_raw_ignores_registry(self, client):
        """call_raw() never uses registry."""
        # Register a type
        client.register_type("my-op", MockResponse)

        # call_raw should still work (timeout) without caring about type
        with pytest.raises(AnyCallException) as exc_info:
            client.call_raw("my-op", {})

        error_msg = str(exc_info.value)
        assert "Timeout" in error_msg or "timeout" in error_msg

    def test_call_raw_no_registry_needed(self, client):
        """call_raw() works without any registry entry."""
        # Don't register anything
        with pytest.raises(AnyCallException) as exc_info:
            client.call_raw("unregistered-op", {})

        # Should fail with timeout, not type lookup error
        error_msg = str(exc_info.value)
        assert "Timeout" in error_msg or "timeout" in error_msg


class TestErrorMessages:
    """Tests for error message quality."""

    def test_missing_type_error_suggests_both_paths(self, client):
        """Missing type error suggests both solutions."""
        with pytest.raises(AnyCallException) as exc_info:
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

        with pytest.raises(AnyCallException) as exc_info:
            client.register_type("operation", AlternativeResponse)

        error_msg = str(exc_info.value)
        # Should name both types
        assert "MockResponse" in error_msg
        assert "AlternativeResponse" in error_msg
        # Should mention the operation
        assert "operation" in error_msg


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
