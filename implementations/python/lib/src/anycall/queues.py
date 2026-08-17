REQUEST_QUEUE_PREFIX = "anycall:requests:"
RESPONSE_QUEUE_PREFIX = "anycall:responses:"


def request_queue(method_name: str) -> str:
    """Generate request queue key for a method."""
    return f"{REQUEST_QUEUE_PREFIX}{method_name}"


def method_name_from_queue(queue_key: str) -> str:
    """Recover the method name from a request queue key."""
    return queue_key[len(REQUEST_QUEUE_PREFIX):]


def response_queue(request_id: str) -> str:
    """Generate response queue key for a request."""
    return f"{RESPONSE_QUEUE_PREFIX}{request_id}"
