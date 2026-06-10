from datetime import timedelta

import redis

from .client import AnyCallClient, AnyCallClientImpl
from .config import AnycallProperties
from .redis_adapter import RedisStreamAdapter
from .server import AnyCallServer, AnyCallServerImpl


class AnyCall:
    """Factory for creating AnyCall clients and servers."""

    @staticmethod
    def client(
        redis_uri: str,
        timeout: timedelta = timedelta(seconds=30),
        metrics_enabled: bool = False
    ) -> AnyCallClient:
        """Create an AnyCall client.

        Args:
            redis_uri: Redis connection URI (e.g., redis://localhost:6379)
            timeout: Request timeout duration
            metrics_enabled: Whether to collect metrics

        Returns:
            AnyCallClient instance
        """
        redis_client = redis.from_url(redis_uri, decode_responses=False)
        redis_adapter = RedisStreamAdapter(redis_client)
        props = AnycallProperties(timeout=timeout, metrics_enabled=metrics_enabled)
        return AnyCallClientImpl(redis_adapter, props)

    @staticmethod
    def server(
        redis_uri: str,
        metrics_enabled: bool = False
    ) -> AnyCallServer:
        """Create an AnyCall server.

        Args:
            redis_uri: Redis connection URI (e.g., redis://localhost:6379)
            metrics_enabled: Whether to collect metrics

        Returns:
            AnyCallServer instance
        """
        redis_client = redis.from_url(redis_uri, decode_responses=False)
        redis_adapter = RedisStreamAdapter(redis_client)
        props = AnycallProperties(metrics_enabled=metrics_enabled)
        return AnyCallServerImpl(redis_adapter, props)
