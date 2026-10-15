import logging
from typing import List, Optional, Protocol, Tuple, runtime_checkable

import redis

logger = logging.getLogger(__name__)

# KEYS[1] = live servers sorted set, ARGV[1] = server id, ARGV[2] = ttl seconds.
# Kept byte-for-byte identical to the Java server's copy.
HEARTBEAT_SCRIPT = """\
local t = redis.call('TIME')
local now = tonumber(t[1]) + tonumber(t[2]) / 1000000
redis.call('ZADD', KEYS[1], string.format('%.6f', now), ARGV[1])
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', string.format('%.6f', now - tonumber(ARGV[2])))
redis.call('EXPIRE', KEYS[1], ARGV[2])
return 1
"""


@runtime_checkable
class RedisQueuePort(Protocol):
    """Structural interface for the subset of queue operations AnyCallClient
    depends on. Lets test doubles (e.g. a mock) satisfy the type without
    inheriting from RedisQueueAdapter."""

    def push(self, queue_key: str, value: str) -> int: ...

    def pop(self, queue_keys: List[str], timeout_seconds: float) -> Optional[Tuple[str, str]]: ...

    def delete(self, key: str) -> int: ...

    def length(self, queue_key: str) -> int: ...

    def heartbeat(self, key: str, member: str, ttl_seconds: int) -> None: ...

    def close(self) -> None: ...


class RedisQueueAdapter:
    """Thin wrapper around Redis List operations, used as AnyCall's request
    and response queues."""

    def __init__(self, redis_client: redis.Redis):
        self.redis = redis_client
        self._heartbeat_script = redis_client.register_script(HEARTBEAT_SCRIPT)

    def push(self, queue_key: str, value: str) -> int:
        """Push a value onto a queue (LPUSH).

        Args:
            queue_key: Redis list key
            value: String value to push

        Returns:
            Length of the queue after the push
        """
        return self.redis.lpush(queue_key, value)

    def pop(self, queue_keys: List[str], timeout_seconds: float) -> Optional[Tuple[str, str]]:
        """Block until one of the given queues has an entry, then pop and
        remove it (BRPOP) -- whichever queue yields data first, paired with
        LPUSH this gives FIFO order per queue.

        Args:
            queue_keys: Redis list keys to block on
            timeout_seconds: Block timeout in seconds (0 blocks indefinitely)

        Returns:
            (queue_key, value) of the popped entry, or None on timeout
        """
        result = self.redis.brpop(queue_keys, timeout_seconds)
        if result is None:
            return None
        key, value = result
        if isinstance(key, bytes):
            key = key.decode("utf-8")
        if isinstance(value, bytes):
            value = value.decode("utf-8")
        return key, value

    def delete(self, key: str) -> int:
        """Delete a key.

        Args:
            key: Key to delete

        Returns:
            Number of keys deleted
        """
        return self.redis.delete(key)

    def length(self, queue_key: str) -> int:
        """Return the number of entries in a queue (LLEN).

        Args:
            queue_key: Redis list key

        Returns:
            Number of entries currently in the queue
        """
        return self.redis.llen(queue_key)

    def heartbeat(self, key: str, member: str, ttl_seconds: int) -> None:
        """Refresh one worker's liveness entry in a sorted set, in a single
        round trip: ZADD the worker under the current time, ZREMRANGEBYSCORE
        away members older than `ttl_seconds` (servers that are gone), then
        push the key's own TTL back out so the whole set disappears on its own
        once every worker is gone.

        Runs as a Lua script so "now" is Redis's own clock (`TIME`), not this
        host's: scores written and pruned by different servers are always
        compared on the same clock, so skew between hosts can't prune a live
        server or keep a dead one around. The script touches a single key, so
        it stays compatible with Redis Cluster.

        Args:
            key: Sorted set key holding the live servers
            member: This worker's id
            ttl_seconds: Members older than this are pruned as dead; also the
                expiry refreshed on the key itself
        """
        self._heartbeat_script(keys=[key], args=[member, ttl_seconds])

    def close(self) -> None:
        """Close Redis connection."""
        self.redis.close()
