REQUEST_QUEUE_PREFIX = "anycall:requests:"
RESPONSE_QUEUE_PREFIX = "anycall:responses:"

# One List per server, holding the requests it is processing. A server moves
# a request here from its method's queue with one BRPOPLPUSH, so a request is
# always in its queue or in exactly one of these -- the key name is the record
# of who has it. The server removes it once the response is written; whoever
# finds the server dead fails back whatever is left (see `reaping`).
PROCESSING_PREFIX = "anycall:processing:"

# Sorted set of server ids heartbeating, scored by Redis's own TIME. Written by
# AnyCallServerImpl, read by clients to tell whether any server is currently
# alive before publishing a request. Members are never pruned by age alone: a
# dead server leaves only when it is reaped (see `reaping`), so its entry is
# how its processing list gets found.
HEARTBEAT_KEY = "anycall:servers:alive"

# How long a heartbeat entry is considered live. Must match the ttl_seconds
# argument the server passes into the heartbeat script, or a client's
# liveness check will disagree with the server's own pruning.
HEARTBEAT_TTL_SECONDS = 8

# Expiry on every response queue, set when a response is written (by a server
# or a reaper). A waiting client pops it within milliseconds and deletes the
# queue; this only matters when nobody reads it (the client timed out or died,
# or a server pruned as dead answered late), so it doesn't sit in Redis forever.
RESPONSE_TTL_SECONDS = 60


def request_queue(method_name: str) -> str:
    """Generate request queue key for a method."""
    return f"{REQUEST_QUEUE_PREFIX}{method_name}"


def method_name_from_queue(queue_key: str) -> str:
    """Recover the method name from a request queue key."""
    return queue_key[len(REQUEST_QUEUE_PREFIX):]


def processing_list(server_id: str) -> str:
    """Generate the processing list key for a server."""
    return f"{PROCESSING_PREFIX}{server_id}"


def response_queue(request_id: str) -> str:
    """Generate response queue key for a request."""
    return f"{RESPONSE_QUEUE_PREFIX}{request_id}"
