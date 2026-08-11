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
        metrics_enabled: bool = False,
        default_max_queue_depth: int | None = None,
    ) -> AnyCallClient:
        """Create an AnyCall client.

        Args:
            redis_uri: Redis connection URI (e.g., redis://localhost:16379)
            timeout: Request timeout duration
            metrics_enabled: Whether to collect metrics
            default_max_queue_depth: Default backlog limit applied to every
                call made by this client (see AnyCallClient.call's
                max_queue_depth); None means unbounded

        Returns:
            AnyCallClient instance
        """
        redis_client = redis.from_url(redis_uri, decode_responses=False)
        redis_adapter = RedisStreamAdapter(redis_client)
        props = AnycallProperties(timeout=timeout, metrics_enabled=metrics_enabled)
        return AnyCallClientImpl(redis_adapter, props, default_max_queue_depth)

    @staticmethod
    def server(
        redis_uri: str,
        metrics_enabled: bool = False,
        max_concurrency: int | None = None,
    ) -> AnyCallServer:
        """Create an AnyCall server.

        Args:
            redis_uri: Redis connection URI (e.g., redis://localhost:16379)
            metrics_enabled: Whether to collect metrics
            max_concurrency: Server-wide cap on requests processed at the same
                time, across every registered @supply method combined; None
                means uncapped

        Returns:
            AnyCallServer instance
        """
        redis_client = redis.from_url(redis_uri, decode_responses=False)
        redis_adapter = RedisStreamAdapter(redis_client)
        props = AnycallProperties(metrics_enabled=metrics_enabled)
        return AnyCallServerImpl(redis_adapter, props, max_concurrency)
