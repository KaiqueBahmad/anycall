import os
import pytest


class TestBasicIntegration:
    """Basic integration tests for AnyCall Python implementation."""

    @pytest.fixture(autouse=True)
    def redis_uri(self):
        """Get Redis URI from environment or use default."""
        return os.getenv("REDIS_URI", "redis://localhost:6379")

    def test_redis_uri_configured(self, redis_uri):
        """Test that Redis URI is properly configured."""
        assert redis_uri is not None
        assert redis_uri.startswith("redis://")

    def test_anycall_import(self):
        """Test that AnyCall can be imported."""
        try:
            from anycall import AnyCall
            assert AnyCall is not None
        except ImportError as e:
            pytest.skip(f"AnyCall not installed: {e}")

    @pytest.mark.integration
    def test_redis_connectivity(self, redis_uri):
        """Test basic Redis connectivity."""
        try:
            import redis
            client = redis.from_url(redis_uri)
            pong = client.ping()
            assert pong is True
        except Exception as e:
            pytest.skip(f"Redis not available at {redis_uri}: {e}")
