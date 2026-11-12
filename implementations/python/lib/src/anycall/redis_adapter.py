import logging
from typing import List, Optional, Protocol, Tuple, runtime_checkable

import redis

logger = logging.getLogger(__name__)

# KEYS[1] = live servers sorted set, ARGV[1] = server id, ARGV[2] = ttl seconds.
# Returns {1 if this server's entry was missing (first tick, or it was reaped as
# dead), followed by every member whose heartbeat is older than the ttl}. Prunes
# nothing: a dead server leaves the set only through CLAIM_SCRIPT, so its
# processing list is never forgotten.
# Kept byte-for-byte identical to the Java server's copy.
HEARTBEAT_SCRIPT = """\
local t = redis.call('TIME')
local now = tonumber(t[1]) + tonumber(t[2]) / 1000000
local added = redis.call('ZADD', KEYS[1], string.format('%.6f', now), ARGV[1])
local result = redis.call('ZRANGEBYSCORE', KEYS[1], '-inf', '(' .. string.format('%.6f', now - tonumber(ARGV[2])))
table.insert(result, 1, added)
return result
"""

# KEYS[1] = live servers sorted set, ARGV[1] = ttl seconds. Returns every member
# whose heartbeat is older than the ttl -- the read-only half of the heartbeat
# script, for clients, which don't heartbeat.
# Kept byte-for-byte identical to the Java client's copy.
STALE_SCRIPT = """\
local t = redis.call('TIME')
local now = tonumber(t[1]) + tonumber(t[2]) / 1000000
return redis.call('ZRANGEBYSCORE', KEYS[1], '-inf', '(' .. string.format('%.6f', now - tonumber(ARGV[1])))
"""

# KEYS[1] = live servers sorted set, KEYS[2] = the server's processing list.
# ARGV[1] = server id, ARGV[2] = ttl seconds. If the server's heartbeat is still
# older than the ttl, removes it from the set, empties its processing list and
# returns what was in it; otherwise returns {} and changes nothing. Atomic, so
# of everyone who finds the same server dead, exactly one gets its requests.
# Kept byte-for-byte identical to the Java copy.
CLAIM_SCRIPT = """\
local score = redis.call('ZSCORE', KEYS[1], ARGV[1])
if not score then return {} end
local t = redis.call('TIME')
local now = tonumber(t[1]) + tonumber(t[2]) / 1000000
if tonumber(score) >= now - tonumber(ARGV[2]) then return {} end
redis.call('ZREM', KEYS[1], ARGV[1])
local items = redis.call('LRANGE', KEYS[2], 0, -1)
redis.call('DEL', KEYS[2])
return items
"""


def _text(value) -> str:
    return value.decode("utf-8") if isinstance(value, bytes) else value


@runtime_checkable
class RedisQueuePort(Protocol):
    """Structural interface for the subset of queue operations AnyCallClient
    depends on. Lets test doubles (e.g. a mock) satisfy the type without
    inheriting from RedisQueueAdapter."""

    def push(self, queue_key: str, value: str) -> int: ...

    def pop(self, queue_keys: List[str], timeout_seconds: float) -> Optional[Tuple[str, str]]: ...

    def delete(self, key: str) -> int: ...

    def length(self, queue_key: str) -> int: ...

    def alive_count(self, key: str, ttl_seconds: int) -> int: ...

    def stale_members(self, key: str, ttl_seconds: int) -> set[str]: ...

    def claim_dead(self, alive_key: str, processing_key: str, server_id: str, ttl_seconds: int) -> List[str]: ...

    def respond(
        self, response_queue: str, value: str, ttl_seconds: int, processing_key: str = "", item: str = ""
    ) -> None: ...

    def close(self) -> None: ...


class RedisQueueAdapter:
    """Thin wrapper around Redis List operations, used as AnyCall's request
    and response queues."""

    def __init__(self, redis_client: redis.Redis):
        self.redis = redis_client
        self._heartbeat_script = redis_client.register_script(HEARTBEAT_SCRIPT)
        self._stale_script = redis_client.register_script(STALE_SCRIPT)
        self._claim_script = redis_client.register_script(CLAIM_SCRIPT)

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
        return _text(key), _text(value)

    def take(self, queue_key: str, processing_key: str, timeout_seconds: int) -> Optional[str]:
        """Block until the queue has a request, then move it onto the
        processing list, in one atomic step (BRPOPLPUSH): there's no moment
        where a request is out of its queue but not yet recorded as taken, so
        a crash can't make one vanish without a trace.

        Reads a single queue and holds its connection while it blocks, so a
        server keeps one connection per method it reads.

        Args:
            queue_key: The method's request queue
            processing_key: This server's processing list
            timeout_seconds: Block timeout in whole seconds (0 blocks forever)

        Returns:
            The request json, or None on timeout
        """
        value = self.redis.brpoplpush(queue_key, processing_key, timeout_seconds)
        return None if value is None else _text(value)

    def respond(
        self,
        response_queue: str,
        value: str,
        ttl_seconds: int,
        processing_key: str = "",
        item: str = "",
    ) -> None:
        """The one way a response is written, by a server or a reaper: LPUSH
        it, set the queue's expiry, and drop its request from the processing
        list, in one pipelined round trip. The push goes first: if the process
        dies before the LREM, the request is failed back as a crash, but the
        client pops the real response before that error (BRPOP takes the
        oldest).

        Args:
            response_queue: The request's response queue
            value: Serialized response
            ttl_seconds: Expiry for the queue, in case nobody ever reads it
            processing_key: Processing list the request was taken onto ('' to
                skip the LREM, e.g. for a reaper, whose claim emptied it)
            item: The request json exactly as it was taken
        """
        pipe = self.redis.pipeline(transaction=False)
        pipe.lpush(response_queue, value)
        pipe.expire(response_queue, ttl_seconds)
        if processing_key:
            pipe.lrem(processing_key, 1, item)
        pipe.execute()

    def release(self, processing_key: str, item: str) -> None:
        """Drop a request from a processing list without answering it (LREM),
        for one with no response queue to answer on.

        Args:
            processing_key: Processing list the request was taken onto
            item: The request json exactly as it was taken
        """
        self.redis.lrem(processing_key, 1, item)

    def claim_dead(self, alive_key: str, processing_key: str, server_id: str, ttl_seconds: int) -> List[str]:
        """Take over a dead server's requests (see CLAIM_SCRIPT): if its
        heartbeat is still older than `ttl_seconds`, remove it from the live
        set and empty its processing list. Several callers can find the same
        server dead at once; exactly one gets its requests, the rest get [].

        Args:
            alive_key: Sorted set key holding the live servers
            processing_key: The dead server's processing list
            server_id: The dead server's id
            ttl_seconds: How old a heartbeat must be to count as dead

        Returns:
            The request json of everything it was processing, or []
        """
        items = self._claim_script(keys=[alive_key, processing_key], args=[server_id, ttl_seconds])
        return [_text(item) for item in items]

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

    def heartbeat(self, key: str, member: str, ttl_seconds: int) -> Tuple[bool, set[str]]:
        """Refresh one server's liveness entry in a sorted set, in a single
        round trip: ZADD the server under the current time and read back the
        members older than `ttl_seconds` (servers that stopped heartbeating).
        It removes none of them: that's left to `claim_dead`, which also
        fails back what they were processing.

        Runs as a Lua script so "now" is Redis's own clock (`TIME`), not this
        host's: scores written and compared by different servers are always
        on the same clock, so skew between hosts can't make a live server
        look dead or a dead one alive. The script touches a single key.

        Args:
            key: Sorted set key holding the live servers
            member: This server's id
            ttl_seconds: Members older than this are dead

        Returns:
            (whether `member` had no entry before this tick, every dead member)
        """
        added, *stale = self._heartbeat_script(keys=[key], args=[member, ttl_seconds])
        return added == 1, {_text(m) for m in stale}

    def alive_count(self, key: str, ttl_seconds: int) -> int:
        """Count members in a heartbeat sorted set still within `ttl_seconds`
        of Redis's own current time (`TIME`), i.e. how many are alive.

        Uses Redis's clock rather than this host's, for the same reason the
        heartbeat script does: skew between hosts can't make a live server
        look dead (or vice versa) to this check.

        Args:
            key: Sorted set key holding the live servers
            ttl_seconds: Members older than this are considered dead

        Returns:
            Number of members scored within the last ttl_seconds
        """
        seconds, microseconds = self.redis.time()
        now = seconds + microseconds / 1_000_000
        return self.redis.zcount(key, now - ttl_seconds, "+inf")

    def stale_members(self, key: str, ttl_seconds: int) -> set[str]:
        """Every member of a heartbeat sorted set older than `ttl_seconds`
        by Redis's own clock (`TIME`), i.e. the dead servers not reaped yet
        -- the read-only half of the heartbeat script, for clients, which
        don't heartbeat.

        Args:
            key: Sorted set key holding the live servers
            ttl_seconds: Members older than this are dead
        """
        return {_text(m) for m in self._stale_script(keys=[key], args=[ttl_seconds])}

    def close(self) -> None:
        """Close Redis connection."""
        self.redis.close()
