import logging
from typing import Dict

from . import queues
from .model import AnyCallResponse
from .serialization import serialize

logger = logging.getLogger(__name__)


def reap_orphans(redis, owners: Dict[str, str], alive: set[str]) -> None:
    """For each in-flight request whose owner isn't alive anymore, push a
    server-lost error to its response queue so the client stops waiting.

    Run by servers on every heartbeat tick (heartbeat reaping) and by a client
    whose calls have gone quiet (waiter-driven reaping). Several of them can
    notice the same dead owner at once; the HDEL is the claim -- only the one
    that actually removes the entry writes the error, so the client never gets
    two.

    `owners` must be read before `alive`: the other way around, a server that
    starts and takes a request in between would look dead.
    """
    for request_id, owner in owners.items():
        if owner in alive:
            continue
        try:
            if not redis.release_inflight(queues.INFLIGHT_KEY, request_id):
                continue
            redis.push_expiring(
                queues.response_queue(request_id),
                serialize(AnyCallResponse.server_lost(request_id, owner)),
                queues.ORPHAN_RESPONSE_TTL_SECONDS,
            )
            logger.warning(f"Failed request {request_id} back to its client: server {owner} is gone")
        except Exception as e:
            logger.warning(f"Failed to fail back request {request_id} of dead server {owner}: {e}")
