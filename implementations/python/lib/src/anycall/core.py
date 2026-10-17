from datetime import timedelta

import redis

from .client import AnyCallClient, AnyCallClientImpl
from .config import AnycallProperties
from .redis_adapter import RedisQueueAdapter
from .server import AnyCallServer, AnyCallServerImpl

# Added on top of the call timeout to get the client's socket read timeout, so
# the socket never gives up on a response BRPOP that is still within its call
# timeout.
SOCKET_TIMEOUT_MARGIN = timedelta(seconds=5)


def _client_socket_timeout(timeout: timedelta) -> float | None:
    """Socket read timeout for a client whose calls wait up to `timeout`.

    redis-py 8 changed the default from no limit to 5s, which cut every call
    waiting longer than that with a TimeoutError. A zero `timeout` means the
    BRPOP blocks forever, so the socket must too.
    """
    if timeout <= timedelta(0):
        return None
    return (timeout + SOCKET_TIMEOUT_MARGIN).total_seconds()


class AnyCall:
    """Factory for creating AnyCall clients and servers."""

    @staticmethod
    def client(
        redis_uri: str,
        timeout: timedelta = timedelta(0),
        metrics_enabled: bool = False,
        default_max_queue_depth: int | None = None,
    ) -> AnyCallClient:
        """Create an AnyCall client.

        Args:
            redis_uri: Redis connection URI (e.g., redis://localhost:16379)
            timeout: How long a call waits for its response; timedelta(0)
                (the default) waits with no limit
            metrics_enabled: Whether to collect metrics
            default_max_queue_depth: Default backlog limit applied to every
                call made by this client (see AnyCallClient.call's
                max_queue_depth); None means unbounded

        Returns:
            AnyCallClient instance
        """
        redis_client = redis.from_url(
            redis_uri, decode_responses=False, socket_timeout=_client_socket_timeout(timeout)
        )
        redis_adapter = RedisQueueAdapter(redis_client)
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
        redis_adapter = RedisQueueAdapter(redis_client)
        props = AnycallProperties(metrics_enabled=metrics_enabled)
        return AnyCallServerImpl(redis_adapter, props, max_concurrency)
