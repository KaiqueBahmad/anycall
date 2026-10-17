REQUEST_QUEUE_PREFIX = "anycall:requests:"
RESPONSE_QUEUE_PREFIX = "anycall:responses:"

# Pub/Sub channel a client publishes to right after pushing a request, so idle
# servers for that method go look at the queue instead of waiting out their
# fallback poll. Carries no data -- it only means "there may be something new".
WAKE_CHANNEL_PREFIX = "anycall:wake:"

# Hash of request id -> id of the server processing it. A server writes the
# entry in the same script that pops the request, and removes it once the
# response is sent; entries whose owner stopped heartbeating are failed back
# to their client by whichever live server notices first.
INFLIGHT_KEY = "anycall:inflight"

# Sorted set of server ids heartbeating, scored by Redis's own TIME. Written by
# AnyCallServerImpl, read by clients to tell whether any server is currently
# alive before publishing a request.
HEARTBEAT_KEY = "anycall:servers:alive"

# How long a heartbeat entry is considered live. Must match the ttl_seconds
# argument the server passes into the heartbeat script, or a client's
# liveness check will disagree with the server's own pruning.
HEARTBEAT_TTL_SECONDS = 8

# Expiry on the error response written for a request whose server died: its
# client may have timed out already, and nothing else would ever delete it.
ORPHAN_RESPONSE_TTL_SECONDS = 60


def request_queue(method_name: str) -> str:
    """Generate request queue key for a method."""
    return f"{REQUEST_QUEUE_PREFIX}{method_name}"


def method_name_from_queue(queue_key: str) -> str:
    """Recover the method name from a request queue key."""
    return queue_key[len(REQUEST_QUEUE_PREFIX):]


def wake_channel(method_name: str) -> str:
    """Generate the wake channel for a method."""
    return f"{WAKE_CHANNEL_PREFIX}{method_name}"


def response_queue(request_id: str) -> str:
    """Generate response queue key for a request."""
    return f"{RESPONSE_QUEUE_PREFIX}{request_id}"
