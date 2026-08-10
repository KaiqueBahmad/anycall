import logging
from typing import Any, Dict, Optional

import redis

logger = logging.getLogger(__name__)


class RedisStreamAdapter:
    """Thin wrapper around Redis Streams operations."""

    def __init__(self, redis_client: redis.Redis):
        self.redis = redis_client

    def add(self, stream_key: str, data: Dict[str, str]) -> str:
        """Add entry to stream.

        Args:
            stream_key: Redis stream key
            data: Dictionary with data to store (must have string values)

        Returns:
            Message ID
        """
        return self.redis.xadd(stream_key, data)

    def read(self, stream_key: str, timeout_ms: int) -> Optional[Any]:
        """Read from stream with timeout (from beginning).

        Args:
            stream_key: Redis stream key
            timeout_ms: Block timeout in milliseconds

        Returns:
            List of (message_id, data_dict) tuples or None if timeout
        """
        result = self.redis.xread(
            {stream_key: "0-0"},
            block=timeout_ms,
            count=1
        )
        return result

    def read_group(
        self,
        stream_key: str,
        group_name: str,
        consumer_id: str,
        timeout_ms: int
    ) -> Optional[Any]:
        """Read from stream using consumer group.

        Args:
            stream_key: Redis stream key
            group_name: Consumer group name
            consumer_id: Consumer ID
            timeout_ms: Block timeout in milliseconds

        Returns:
            List of (message_id, data_dict) tuples or None if timeout
        """
        result = self.redis.xreadgroup(
            groupname=group_name,
            consumername=consumer_id,
            streams={stream_key: ">"},
            block=timeout_ms,
            count=1
        )
        return result

    def create_group(self, stream_key: str, group_name: str) -> None:
        """Create consumer group on stream.

        Handles BUSYGROUP and missing stream errors gracefully.

        Args:
            stream_key: Redis stream key
            group_name: Consumer group name
        """
        try:
            self.redis.xgroup_create(stream_key, group_name, id="$", mkstream=True)
        except redis.ResponseError as e:
            if "BUSYGROUP" in str(e):
                pass
            else:
                raise

    def acknowledge(self, stream_key: str, group_name: str, message_id: str) -> int:
        """Acknowledge message in consumer group.

        Args:
            stream_key: Redis stream key
            group_name: Consumer group name
            message_id: Message ID to acknowledge

        Returns:
            Number of messages acknowledged
        """
        return self.redis.xack(stream_key, group_name, message_id)

    def delete(self, key: str) -> int:
        """Delete a key.

        Args:
            key: Key to delete

        Returns:
            Number of keys deleted
        """
        return self.redis.delete(key)

    def delete_entry(self, stream_key: str, message_id: str) -> int:
        """Delete a single entry from a stream (XDEL).

        Args:
            stream_key: Redis stream key
            message_id: Message ID to remove

        Returns:
            Number of entries deleted
        """
        return self.redis.xdel(stream_key, message_id)

    def length(self, stream_key: str) -> int:
        """Return the number of entries in a stream (XLEN).

        Args:
            stream_key: Redis stream key

        Returns:
            Number of entries currently in the stream
        """
        return self.redis.xlen(stream_key)

    def set_with_ttl(self, key: str, value: str, ttl_seconds: int) -> None:
        """Set a key with an expiry (used for server heartbeats).

        Args:
            key: Key to set
            value: Value to store
            ttl_seconds: Expiry in seconds
        """
        self.redis.set(key, value, ex=ttl_seconds)

    def close(self) -> None:
        """Close Redis connection."""
        self.redis.close()
