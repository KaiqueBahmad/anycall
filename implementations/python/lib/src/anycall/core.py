from datetime import timedelta

import redis

from .client import WAITER_REAP_SLICE_SECONDS, AnyCallClient, AnyCallClientImpl
from .redis_adapter import RedisQueueAdapter
from .server import AnyCallServer, AnyCallServerImpl

# Added on top of a wait slice to get the client's socket read timeout: no
# command blocks longer than a slice, so one that outlasts this is stuck on a
# Redis that stopped answering, and fails as a BrokerError.
SOCKET_TIMEOUT_MARGIN = timedelta(seconds=5)

# redis-py 8 changed the default from no limit to 5s, which would cut a wait
# slice short. Every BRPOP lasts a slice at most, whatever the call's timeout,
# so a call with no limit still never blocks on a dead Redis forever.
# RESP2: redis-py 8 opens every connection with HELLO 3, which Redis 5 doesn't
# have.
REDIS_PROTOCOL = 2

CLIENT_SOCKET_TIMEOUT = (timedelta(seconds=WAITER_REAP_SLICE_SECONDS) + SOCKET_TIMEOUT_MARGIN).total_seconds()


class AnyCall:
    """Factory for creating AnyCall clients and servers."""

    @staticmethod
    def client(
        redis_uri: str,
        timeout: timedelta = timedelta(0),
        default_max_queue_depth: int | None = None,
    ) -> AnyCallClient:
        """Create an AnyCall client.

        Args:
            redis_uri: Redis connection URI (e.g., redis://localhost:16379)
            timeout: How long a call waits for its response; timedelta(0)
                (the default) waits with no limit
            default_max_queue_depth: Default backlog limit applied to every
                call made by this client (see AnyCallClient.call's
                max_queue_depth); None means unbounded

        Returns:
            AnyCallClient instance
        """
        redis_client = redis.from_url(
            redis_uri, decode_responses=False, socket_timeout=CLIENT_SOCKET_TIMEOUT, protocol=REDIS_PROTOCOL
        )
        redis_adapter = RedisQueueAdapter(redis_client)
        return AnyCallClientImpl(redis_adapter, timeout, default_max_queue_depth)

    @staticmethod
    def server(
        redis_uri: str,
        max_concurrency: int | None = None,
    ) -> AnyCallServer:
        """Create an AnyCall server.

        Args:
            redis_uri: Redis connection URI (e.g., redis://localhost:16379)
            max_concurrency: Server-wide cap on requests processed at the same
                time, across every registered @supply method combined; None
                means uncapped

        Returns:
            AnyCallServer instance
        """
        redis_client = redis.from_url(redis_uri, decode_responses=False, protocol=REDIS_PROTOCOL)
        redis_adapter = RedisQueueAdapter(redis_client)
        return AnyCallServerImpl(redis_adapter, max_concurrency)
