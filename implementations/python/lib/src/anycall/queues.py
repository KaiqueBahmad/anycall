REQUEST_QUEUE_PREFIX = "anycall:requests:"
RESPONSE_QUEUE_PREFIX = "anycall:responses:"

# Sorted set of server ids heartbeating, scored by Redis's own TIME. Written by
# AnyCallServerImpl, read by clients to tell whether any server is currently
# alive before publishing a request.
HEARTBEAT_KEY = "anycall:servers:alive"

# How long a heartbeat entry is considered live. Must match the ttl_seconds
# argument the server passes into the heartbeat script, or a client's
# liveness check will disagree with the server's own pruning.
HEARTBEAT_TTL_SECONDS = 8


def request_queue(method_name: str) -> str:
    """Generate request queue key for a method."""
    return f"{REQUEST_QUEUE_PREFIX}{method_name}"


def method_name_from_queue(queue_key: str) -> str:
    """Recover the method name from a request queue key."""
    return queue_key[len(REQUEST_QUEUE_PREFIX):]


def response_queue(request_id: str) -> str:
    """Generate response queue key for a request."""
    return f"{RESPONSE_QUEUE_PREFIX}{request_id}"
