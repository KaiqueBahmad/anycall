import logging
from typing import Callable, List, Optional, Protocol, Tuple, runtime_checkable

import redis

logger = logging.getLogger(__name__)

# KEYS[1] = live servers sorted set, ARGV[1] = server id, ARGV[2] = ttl seconds,
# ARGV[3] = '1' on the server id's first heartbeat. A server whose entry is gone,
# or older than the ttl, was declared dead: past its first heartbeat, it gets
# {-1} and nothing is written, so a dead server never comes back. Otherwise
# refreshes its entry and returns {0, every member older than the ttl}. Prunes
# nothing: a dead server leaves the set only once `fail_back_next` has emptied
# its processing list, so that list is never forgotten.
# Kept byte-for-byte identical to the Java server's copy.
HEARTBEAT_SCRIPT = """\
local t = redis.call('TIME')
local now = tonumber(t[1]) + tonumber(t[2]) / 1000000
local stale = string.format('%.6f', now - tonumber(ARGV[2]))
if ARGV[3] ~= '1' then
  local score = redis.call('ZSCORE', KEYS[1], ARGV[1])
  if not score or tonumber(score) < tonumber(stale) then return {-1} end
end
redis.call('ZADD', KEYS[1], string.format('%.6f', now), ARGV[1])
local result = redis.call('ZRANGEBYSCORE', KEYS[1], '-inf', '(' .. stale)
table.insert(result, 1, 0)
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

# KEYS[1] = live servers sorted set, KEYS[2] = a dead server's processing list.
# ARGV[1] = server id, ARGV[2] = tombstone ttl seconds. The last step of reaping
# a dead server: if its list is still empty, removes it from the live set and,
# if it was still there, turns the list into a tombstone string. Returns 0 if a
# request landed on the list meanwhile (keep reaping), else 1. A server whose
# entry is already gone was reaped before; its tombstone isn't recreated, in
# case the server came back and deleted it.
# Kept byte-for-byte identical to the Java copy.
TOMBSTONE_SCRIPT = """\
local kind = redis.call('TYPE', KEYS[2])['ok']
if kind == 'list' then return 0 end
if redis.call('ZREM', KEYS[1], ARGV[1]) == 1 and kind == 'none' then
  redis.call('SET', KEYS[2], 'drained', 'EX', ARGV[2])
end
return 1
"""

# KEYS[1] = a server's own processing list. Deletes it only if it's a
# tombstone: a server that drained deletes its own once nothing can take onto
# that list anymore.
# Kept byte-for-byte identical to the Java copy.
DROP_TOMBSTONE_SCRIPT = """\
if redis.call('TYPE', KEYS[1])['ok'] == 'string' then return redis.call('DEL', KEYS[1]) end
return 0
"""


# What a reaping step returns when someone changed the list meanwhile: look
# again. (Its other results are "answered", "dropped", or None once done.)
_RETRY = "retry"


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

    def fail_back_next(
        self,
        alive_key: str,
        processing_key: str,
        server_id: str,
        response_ttl_seconds: int,
        tombstone_ttl_seconds: int,
        response_for: Callable[[str], Optional[Tuple[str, str]]],
    ) -> Optional[str]: ...

    def respond(
        self, response_queue: str, value: str, ttl_seconds: int, processing_key: str = "", item: str = ""
    ) -> None: ...

    def close(self) -> None: ...


class RedisQueueAdapter:
    """Thin wrapper around Redis List operations, used as AnyCall's request
    and response queues."""

    def __init__(self, redis_client: redis.Redis):
        self.redis = redis_client
        # Set by `detect_blmove`, which a server runs once on start.
        self._blmove = False
        self._heartbeat_script = redis_client.register_script(HEARTBEAT_SCRIPT)
        self._stale_script = redis_client.register_script(STALE_SCRIPT)
        self._tombstone_script = redis_client.register_script(TOMBSTONE_SCRIPT)
        self._drop_tombstone_script = redis_client.register_script(DROP_TOMBSTONE_SCRIPT)

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

    def detect_blmove(self) -> bool:
        """Ask Redis whether it has BLMOVE (6.2+), and take with it from now
        on if so; BRPOPLPUSH, which 6.2 deprecates, otherwise. Asks for the
        command rather than reading the version, which servers compatible
        with Redis don't always report faithfully.

        Reads the reply raw: redis-py's parser for COMMAND INFO breaks on the
        nil a Redis without the command answers.

        Returns:
            Whether BLMOVE is used
        """
        connection = self.redis.connection_pool.get_connection()
        try:
            connection.send_command("COMMAND", "INFO", "BLMOVE")
            reply = connection.read_response()
        finally:
            self.redis.connection_pool.release(connection)
        self._blmove = bool(reply) and reply[0] is not None
        return self._blmove

    def take(self, queue_key: str, processing_key: str, timeout_seconds: int) -> Optional[str]:
        """Block until the queue has a request, then move it onto the
        processing list, in one atomic step (BLMOVE, or BRPOPLPUSH on a Redis
        without it; see `detect_blmove`): there's no moment where a request
        is out of its queue but not yet recorded as taken, so a crash can't
        make one vanish without a trace.

        Reads a single queue and holds its connection while it blocks, so a
        server keeps one connection per method it reads.

        Args:
            queue_key: The method's request queue
            processing_key: This server's processing list
            timeout_seconds: Block timeout in whole seconds (0 blocks forever)

        Returns:
            The request json, or None on timeout
        """
        if self._blmove:
            value = self.redis.blmove(queue_key, processing_key, timeout_seconds, "RIGHT", "LEFT")
        else:
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
                skip the LREM)
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

    def fail_back_next(
        self,
        alive_key: str,
        processing_key: str,
        server_id: str,
        response_ttl_seconds: int,
        tombstone_ttl_seconds: int,
        response_for: Callable[[str], Optional[Tuple[str, str]]],
    ) -> Optional[str]:
        """One step of reaping a dead server: fail back its next request, or,
        once its list is empty, leave a tombstone. Looks at the server's
        processing key and picks the case:

        - a string: a tombstone, the server was reaped before;
        - a list: there are requests left (see `_fail_back_last`);
        - nothing: the list is empty (see `_tombstone`).

        WATCH on the key makes any change by another reaper meanwhile restart
        the step.

        Args:
            alive_key: Sorted set key holding the live servers
            processing_key: The dead server's processing list
            server_id: The dead server's id
            response_ttl_seconds: Expiry for the response queue
            tombstone_ttl_seconds: Expiry for the tombstone its list becomes
            response_for: Gives the (response queue, response) for a request,
                or None for one with no readable requestId, which is dropped

        Returns:
            "answered" or "dropped" for the request it took, or None once
            there's nothing left: the server's list is a tombstone now.
        """
        while True:
            with self.redis.pipeline() as pipe:
                pipe.watch(processing_key)
                kind = _text(pipe.type(processing_key))
                if kind == "string":
                    return None
                if kind == "list":
                    step = self._fail_back_last(pipe, processing_key, response_ttl_seconds, response_for)
                else:
                    step = self._tombstone(alive_key, processing_key, server_id, tombstone_ttl_seconds)
            if step != _RETRY:
                return step

    def _fail_back_last(
        self,
        pipe,
        processing_key: str,
        response_ttl_seconds: int,
        response_for: Callable[[str], Optional[Tuple[str, str]]],
    ) -> Optional[str]:
        """Fail back the last request on a dead server's list: remove it and
        write its server-lost response in one transaction, so it never leaves
        the list unanswered.

        The request is read with a plain LINDEX, outside any script, so Redis
        is never blocked copying it into Lua. The WATCH guarantees it's still
        the last one when the transaction runs, so it's removed by position
        (LTRIM), with nothing to compare or send back; if another reaper took
        it first, the transaction is discarded.
        """
        request = pipe.lindex(processing_key, -1)
        if request is None:
            return _RETRY  # emptied meanwhile: the next look tombstones it
        target = response_for(_text(request))

        pipe.multi()
        pipe.ltrim(processing_key, 0, -2)
        if target is not None:
            response_queue, response = target
            pipe.lpush(response_queue, response)
            pipe.expire(response_queue, response_ttl_seconds)
        try:
            pipe.execute()
        except redis.exceptions.WatchError:
            return _RETRY
        return "dropped" if target is None else "answered"

    def _tombstone(self, alive_key: str, processing_key: str, server_id: str, tombstone_ttl_seconds: int) -> Optional[str]:
        """The last step of reaping a dead server, once its list is empty:
        TOMBSTONE_SCRIPT removes it from the live set and turns its processing
        key into a tombstone. If a request landed on the list meanwhile, the
        script changes nothing, and reaping goes on."""
        done = self._tombstone_script(keys=[alive_key, processing_key], args=[server_id, tombstone_ttl_seconds])
        return None if done else _RETRY

    def drop_tombstone(self, processing_key: str) -> None:
        """Delete a server's own tombstone (see DROP_TOMBSTONE_SCRIPT); does
        nothing if the key isn't one."""
        self._drop_tombstone_script(keys=[processing_key])

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

    def heartbeat(self, key: str, member: str, ttl_seconds: int, first: bool) -> Optional[set[str]]:
        """Refresh one server's liveness entry in a sorted set, in a single
        round trip, and read back the members older than `ttl_seconds`
        (servers that stopped heartbeating). It removes none of them: that's
        left to `fail_back_next`, which also fails back what they were
        processing.

        Past its first heartbeat, a server whose entry is gone or older than
        `ttl_seconds` was declared dead, and gets None: nothing is written,
        so it never comes back under that id. The check and the write are one
        script, so no reaper can act in between.

        Runs as a Lua script so "now" is Redis's own clock (`TIME`), not this
        host's: scores written and compared by different servers are always
        on the same clock, so skew between hosts can't make a live server
        look dead or a dead one alive. The script touches a single key.

        Args:
            key: Sorted set key holding the live servers
            member: This server's id
            ttl_seconds: Members older than this are dead
            first: Whether this is `member`'s first heartbeat

        Returns:
            Every dead member, or None if `member` itself was declared dead
        """
        status, *stale = self._heartbeat_script(keys=[key], args=[member, ttl_seconds, "1" if first else "0"])
        if status == -1:
            return None
        return {_text(m) for m in stale}

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
