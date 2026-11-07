import json
import logging
from typing import Iterable

from . import queues
from .model import AnyCallRequest, AnyCallResponse
from .serialization import serialize

logger = logging.getLogger(__name__)


def reap_dead_servers(redis, dead: Iterable[str]) -> None:
    """For each server that stopped heartbeating, push a server-lost error to
    the response queue of every request still on its processing list, so
    their clients stop waiting.

    Run by servers on every heartbeat tick and by clients whenever a wait for
    a response ends empty -- the same code either way. Several of them can
    find the same dead server at once; `claim_dead` is the claim -- it hands
    the server's requests to exactly one of them, and only that one writes
    the errors, so a client never gets two.

    `dead` is only a hint (members whose heartbeat looked old when it was
    read): `claim_dead` checks again, atomically, so a server that heartbeated
    in between is left alone.
    """
    for server_id in dead:
        try:
            items = redis.claim_dead(
                queues.HEARTBEAT_KEY,
                queues.processing_list(server_id),
                server_id,
                queues.HEARTBEAT_TTL_SECONDS,
            )
        except Exception as e:
            logger.warning(f"Failed to reap dead server {server_id}: {e}")
            continue
        for item in items:
            _fail_back(redis, item, server_id)


def _fail_back(redis, item: str, server_id: str) -> None:
    try:
        request_id = AnyCallRequest.from_dict(json.loads(item)).request_id
    except Exception:
        logger.warning(f"Dropped an unparseable request of dead server {server_id}")
        return
    try:
        redis.respond(
            queues.response_queue(request_id),
            serialize(AnyCallResponse.server_lost(request_id, server_id)),
            queues.RESPONSE_TTL_SECONDS,
        )
        logger.warning(f"Failed request {request_id} back to its client: server {server_id} is gone")
    except Exception as e:
        logger.warning(f"Failed to fail back request {request_id} of dead server {server_id}: {e}")
