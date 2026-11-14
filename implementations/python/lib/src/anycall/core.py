from datetime import timedelta

import redis

from .options import DEFAULT_CALL_OPTIONS, DEFAULT_SERVER_OPTIONS, CallOptions, ServerOptions
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
    def client(redis_url: str, defaults: CallOptions = DEFAULT_CALL_OPTIONS) -> AnyCallClient:
        """Create an AnyCall client.

        Args:
            redis_url: Redis connection URL (e.g., redis://localhost:16379)
            defaults: The settings of every call the client makes; a setting
                left out means no limit, and a call's own CallOptions replace
                them

        Returns:
            AnyCallClient instance
        """
        redis_client = redis.from_url(
            redis_url, decode_responses=False, socket_timeout=CLIENT_SOCKET_TIMEOUT, protocol=REDIS_PROTOCOL
        )
        redis_adapter = RedisQueueAdapter(redis_client)
        return AnyCallClientImpl(redis_adapter, defaults)

    @staticmethod
    def server(redis_url: str, options: ServerOptions = DEFAULT_SERVER_OPTIONS) -> AnyCallServer:
        """Create an AnyCall server.

        Args:
            redis_url: Redis connection URL (e.g., redis://localhost:16379)
            options: The server's settings; see ServerOptions

        Returns:
            AnyCallServer instance
        """
        redis_client = redis.from_url(redis_url, decode_responses=False, protocol=REDIS_PROTOCOL)
        redis_adapter = RedisQueueAdapter(redis_client)
        return AnyCallServerImpl(redis_adapter, options.max_concurrency)
