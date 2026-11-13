import logging
from typing import Iterable, Optional, Tuple

from . import queues
from .model import AnyCallResponse, read_request_id
from .serialization import serialize

logger = logging.getLogger(__name__)


def reap_dead_servers(redis, dead: Iterable[str]) -> None:
    """For each server that stopped heartbeating, push a server-lost error to
    the response queue of every request still on its processing list, so
    their clients stop waiting.

    Run by servers on every heartbeat tick and by clients whenever a wait for
    a response ends empty -- the same code either way. Each request is
    failed back in a transaction of its own (see
    `RedisQueueAdapter.fail_back_next`): it leaves the list only together
    with its response, so a reaper that dies halfway loses nothing, and of
    several reapers on the same server, each request goes to exactly one.

    A server declared dead never heartbeats again (see
    `RedisQueueAdapter.heartbeat`), so there's nothing to check about it
    first.
    """
    for server_id in dead:
        answered = dropped = 0
        try:
            while True:
                outcome = redis.fail_back_next(
                    queues.HEARTBEAT_KEY,
                    queues.processing_list(server_id),
                    server_id,
                    queues.RESPONSE_TTL_SECONDS,
                    queues.TOMBSTONE_TTL_SECONDS,
                    lambda item: _server_lost(item, server_id),
                )
                if outcome is None:
                    break
                if outcome == "answered":
                    answered += 1
                else:
                    dropped += 1
        except Exception as e:
            logger.warning(f"Failed to reap dead server {server_id}: {e}")
        if answered:
            logger.warning(f"Failed back {answered} request(s) of dead server {server_id} to their clients")
        if dropped:
            logger.warning(f"Dropped {dropped} request(s) with no readable requestId of dead server {server_id}")


def _server_lost(item: str, server_id: str) -> Optional[Tuple[str, str]]:
    """The response queue and server-lost response for a request of a dead
    server, or None if its requestId can't be read.

    Only the requestId is needed, so a request the server couldn't have
    parsed (an unknown field, say) still reaches its client.
    """
    request_id = read_request_id(item)
    if request_id is None:
        return None
    return (
        queues.response_queue(request_id),
        serialize(AnyCallResponse.server_lost(request_id, server_id)),
    )
