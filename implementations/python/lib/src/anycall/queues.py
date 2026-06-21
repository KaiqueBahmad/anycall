REQUEST_QUEUE_PREFIX = "anycall:requests:"
RESPONSE_QUEUE_PREFIX = "anycall:responses:"
CONSUMER_GROUP_PREFIX = "anycall-workers"


def request_queue(method_name: str) -> str:
    """Generate request stream key for a method."""
    return f"{REQUEST_QUEUE_PREFIX}{method_name}"


def response_queue(request_id: str) -> str:
    """Generate response stream key for a request."""
    return f"{RESPONSE_QUEUE_PREFIX}{request_id}"


def consumer_group(method_name: str) -> str:
    """Generate consumer group name for a method."""
    return f"{CONSUMER_GROUP_PREFIX}:{method_name}"
