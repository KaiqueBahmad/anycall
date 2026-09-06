import logging
from typing import List, Optional, Protocol, Tuple, runtime_checkable

import redis

logger = logging.getLogger(__name__)


@runtime_checkable
class RedisQueuePort(Protocol):
    """Structural interface for the subset of queue operations AnyCallClient
    depends on. Lets test doubles (e.g. a mock) satisfy the type without
    inheriting from RedisQueueAdapter."""

    def push(self, queue_key: str, value: str) -> int: ...

    def pop(self, queue_keys: List[str], timeout_seconds: float) -> Optional[Tuple[str, str]]: ...

    def delete(self, key: str) -> int: ...

    def length(self, queue_key: str) -> int: ...

    def heartbeat(
        self,
        key: str,
        member: str,
        score: float,
        ttl_seconds: int,
        min_score: float,
    ) -> None: ...

    def remove_member(self, key: str, member: str) -> int: ...

    def close(self) -> None: ...


class RedisQueueAdapter:
    """Thin wrapper around Redis List operations, used as AnyCall's request
    and response queues."""

    def __init__(self, redis_client: redis.Redis):
        self.redis = redis_client

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

    def heartbeat(
        self,
        key: str,
        member: str,
        score: float,
        ttl_seconds: int,
        min_score: float,
    ) -> None:
        """Refresh one worker's liveness entry in a sorted set, in a single
        round trip: ZADD the worker under its current timestamp, ZREMRANGEBYSCORE
        away members whose timestamp is older than `min_score` (servers that died
        without deregistering), then push the key's own TTL back out so the whole
        set disappears on its own once every worker is gone.

        No transaction semantics (MULTI/EXEC) are needed: the three commands touch
        a single key and none depends on another's result, so a plain pipeline is
        enough and it stays compatible with Redis Cluster.

        Args:
            key: Sorted set key holding the live servers
            member: This worker's id
            score: Timestamp to record for this worker (epoch seconds)
            ttl_seconds: Expiry refreshed on the key itself
            min_score: Members scored at or below this are pruned as dead
        """
        pipe = self.redis.pipeline(transaction=False)
        pipe.zadd(key, {member: score})
        pipe.zremrangebyscore(key, "-inf", min_score)
        pipe.expire(key, ttl_seconds)
        pipe.execute()

    def remove_member(self, key: str, member: str) -> int:
        """Remove a member from a sorted set (ZREM), used to deregister a worker
        on a clean shutdown instead of waiting for it to age out.

        Args:
            key: Sorted set key
            member: Member to remove

        Returns:
            Number of members removed
        """
        return self.redis.zrem(key, member)

    def close(self) -> None:
        """Close Redis connection."""
        self.redis.close()
