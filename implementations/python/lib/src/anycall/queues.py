REQUEST_QUEUE_PREFIX = "anycall:requests:"
RESPONSE_QUEUE_PREFIX = "anycall:responses:"
# Shared literal group name across every method's stream (not suffixed with
# the method name) -- matches the Java implementation and is required for a
# single XREADGROUP call to cover multiple streams at once, since Redis only
# accepts one group name per call. Redis scopes a group by (stream, name), so
# reusing the same name across streams doesn't couple the methods together.
CONSUMER_GROUP_PREFIX = "anycall-workers"


def request_queue(method_name: str) -> str:
    """Generate request stream key for a method."""
    return f"{REQUEST_QUEUE_PREFIX}{method_name}"


def method_name_from_stream(stream_key: str) -> str:
    """Recover the method name from a request stream key."""
    return stream_key[len(REQUEST_QUEUE_PREFIX):]


def response_queue(request_id: str) -> str:
    """Generate response stream key for a request."""
    return f"{RESPONSE_QUEUE_PREFIX}{request_id}"
