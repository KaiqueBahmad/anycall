import logging
from typing import List, Optional, Protocol, Tuple, runtime_checkable

import redis
from redis.client import PubSub

logger = logging.getLogger(__name__)

# KEYS[1] = live servers sorted set, ARGV[1] = server id, ARGV[2] = ttl seconds.
# Returns {1 if this server's entry was missing (first tick, or it was pruned as
# dead), followed by every member still alive after the prune}.
# Kept byte-for-byte identical to the Java server's copy.
HEARTBEAT_SCRIPT = """\
local t = redis.call('TIME')
local now = tonumber(t[1]) + tonumber(t[2]) / 1000000
local added = redis.call('ZADD', KEYS[1], string.format('%.6f', now), ARGV[1])
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', string.format('%.6f', now - tonumber(ARGV[2])))
redis.call('EXPIRE', KEYS[1], ARGV[2])
local result = redis.call('ZRANGE', KEYS[1], 0, -1)
table.insert(result, 1, added)
return result
"""

# KEYS[1] = in-flight hash, KEYS[2..n] = request queues to try, in order.
# ARGV[1] = server id. Returns {queue, request json, request id} for the first
# queue with an entry, or {} if all were empty. The request id is '' if the
# entry isn't a parseable request -- then it isn't recorded as in flight.
# Kept byte-for-byte identical to the Java server's copy.
ACQUIRE_SCRIPT = """\
for i = 2, #KEYS do
  local item = redis.call('RPOP', KEYS[i])
  if item then
    local ok, request = pcall(cjson.decode, item)
    local id = ''
    if ok and type(request) == 'table' and type(request.requestId) == 'string' then
      id = request.requestId
      redis.call('HSET', KEYS[1], id, ARGV[1])
    end
    return {KEYS[i], item, id}
  end
end
return {}
"""


def _text(value) -> str:
    return value.decode("utf-8") if isinstance(value, bytes) else value


@runtime_checkable
class RedisQueuePort(Protocol):
    """Structural interface for the subset of queue operations AnyCallClient
    depends on. Lets test doubles (e.g. a mock) satisfy the type without
    inheriting from RedisQueueAdapter."""

    def push_and_wake(self, queue_key: str, value: str, channel: str) -> None: ...

    def pop(self, queue_keys: List[str], timeout_seconds: float) -> Optional[Tuple[str, str]]: ...

    def delete(self, key: str) -> int: ...

    def length(self, queue_key: str) -> int: ...

    def alive_count(self, key: str, ttl_seconds: int) -> int: ...

    def close(self) -> None: ...


class RedisQueueAdapter:
    """Thin wrapper around Redis List operations, used as AnyCall's request
    and response queues."""

    def __init__(self, redis_client: redis.Redis):
        self.redis = redis_client
        self._heartbeat_script = redis_client.register_script(HEARTBEAT_SCRIPT)
        self._acquire_script = redis_client.register_script(ACQUIRE_SCRIPT)

    def push(self, queue_key: str, value: str) -> int:
        """Push a value onto a queue (LPUSH).

        Args:
            queue_key: Redis list key
            value: String value to push

        Returns:
            Length of the queue after the push
        """
        return self.redis.lpush(queue_key, value)

    def push_and_wake(self, queue_key: str, value: str, channel: str) -> None:
        """LPUSH a request and PUBLISH on its wake channel, pipelined into one
        round trip (no MULTI/EXEC: the publish is only a hint, and a server
        that misses it still finds the entry on its fallback poll).

        Args:
            queue_key: Redis list key
            value: String value to push
            channel: Wake channel for the queue's method
        """
        pipe = self.redis.pipeline(transaction=False)
        pipe.lpush(queue_key, value)
        pipe.publish(channel, "1")
        pipe.execute()

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

    def acquire(
        self, inflight_key: str, queue_keys: List[str], owner: str
    ) -> Optional[Tuple[str, str, str]]:
        """Pop the next request from the first non-empty queue and record
        `owner` as processing it, atomically (see ACQUIRE_SCRIPT): there's no
        moment where a request is out of its queue but not yet in the
        in-flight hash, so a crash can't make one vanish without a trace.

        Doesn't block -- returns None straight away if every queue is empty.

        Args:
            inflight_key: Hash of request id -> owning server id
            queue_keys: Request queues to try, in order
            owner: This server's id

        Returns:
            (queue_key, request json, request id) or None. The request id is
            '' if the entry wasn't a parseable request.
        """
        result = self._acquire_script(keys=[inflight_key, *queue_keys], args=[owner])
        if not result:
            return None
        queue_key, value, request_id = result
        return _text(queue_key), _text(value), _text(request_id)

    def respond(self, response_queue: str, value: str, inflight_key: str, request_id: str) -> None:
        """LPUSH a response and drop its request from the in-flight hash, in
        one pipelined round trip. The push goes first: if the process dies in
        between, the entry is failed back as a crash, but the client pops the
        real response before that error (BRPOP takes the oldest).

        Args:
            response_queue: The request's response queue
            value: Serialized response
            inflight_key: Hash of request id -> owning server id
            request_id: Id the request was acquired under ('' to skip the HDEL)
        """
        pipe = self.redis.pipeline(transaction=False)
        pipe.lpush(response_queue, value)
        if request_id:
            pipe.hdel(inflight_key, request_id)
        pipe.execute()

    def inflight_owners(self, inflight_key: str) -> dict[str, str]:
        """Every in-flight request id with the id of the server processing it.

        Args:
            inflight_key: Hash of request id -> owning server id
        """
        return {_text(k): _text(v) for k, v in self.redis.hgetall(inflight_key).items()}

    def release_inflight(self, inflight_key: str, request_id: str) -> bool:
        """HDEL one in-flight entry. Returns whether this call removed it --
        only one caller ever gets True for a given entry, which is what makes
        it safe as a claim when several servers notice the same dead owner.

        Args:
            inflight_key: Hash of request id -> owning server id
            request_id: Request to drop
        """
        return self.redis.hdel(inflight_key, request_id) == 1

    def push_expiring(self, queue_key: str, value: str, ttl_seconds: int) -> None:
        """LPUSH a value and set the list's expiry, pipelined. For responses
        nobody may be waiting for anymore (the client could have timed out
        already), so they don't sit in Redis forever.

        Args:
            queue_key: Redis list key
            value: String value to push
            ttl_seconds: Expiry for the list
        """
        pipe = self.redis.pipeline(transaction=False)
        pipe.lpush(queue_key, value)
        pipe.expire(queue_key, ttl_seconds)
        pipe.execute()

    def subscriber(self) -> PubSub:
        """A fresh Pub/Sub handle on its own connection, with subscribe
        confirmations filtered out. Not thread-safe -- keep it to one thread."""
        return self.redis.pubsub(ignore_subscribe_messages=True)

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
        """Refresh one worker's liveness entry in a sorted set, in a single
        round trip: ZADD the worker under the current time, ZREMRANGEBYSCORE
        away members older than `ttl_seconds` (servers that are gone), push
        the key's own TTL back out so the whole set disappears on its own
        once every worker is gone, and read back who's left.

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

        Returns:
            (whether `member` had no entry before this tick, every live member)
        """
        added, *alive = self._heartbeat_script(keys=[key], args=[member, ttl_seconds])
        return added == 1, {_text(m) for m in alive}

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

    def close(self) -> None:
        """Close Redis connection."""
        self.redis.close()
