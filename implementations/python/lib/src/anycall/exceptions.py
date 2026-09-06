class AnyCallError(Exception):
    """Base exception for all AnyCall framework errors."""

    def __init__(self, service: str, message: str):
        self.service = service
        self.message = message
        super().__init__(message)


class ChannelError(AnyCallError):
    """Communication/infrastructure error."""
    pass


class TimeoutError(ChannelError):
    """Worker did not respond within time limit."""

    def __init__(
        self, service: str, message: str, timeout_ms: int, call_id: str, ttl_timestamp: int
    ):
        super().__init__(service, message)
        self.timeout_ms = timeout_ms
        self.call_id = call_id
        self.ttl_timestamp = ttl_timestamp

    def get_timeout_ms(self) -> int:
        return self.timeout_ms

    def get_id(self) -> str:
        return self.call_id

    def get_ttl_timestamp(self) -> int:
        return self.ttl_timestamp


class QueueFullError(ChannelError):
    """Raised when a call is rejected at submission because the target method's
    request stream already has at least max_queue_depth entries.

    Thrown before the request is published (before XADD), so the caller that
    would have waited for a response is the one that sees the failure --
    instead of the request silently being dropped later by stream trimming
    with no way to signal the original caller.

    The depth check (XLEN then XADD) is advisory, not a hard bound: another
    client can publish between the two calls, so the queue can briefly exceed
    max_queue_depth. A strict bound would need an atomic check-and-add (e.g. a
    Lua script).
    """

    def __init__(self, method_name: str, queue_depth: int, max_queue_depth: int):
        super().__init__(
            "AnyCall",
            f"Queue for method '{method_name}' is full: depth={queue_depth} "
            f">= max_queue_depth={max_queue_depth}",
        )
        self.method_name = method_name
        self.queue_depth = queue_depth
        self.max_queue_depth = max_queue_depth


class RemoteExecutionError(AnyCallError):
    """Function was executed but failed on worker."""
    pass


class RemoteException(RemoteExecutionError):
    """Worker died during execution."""

    def __init__(self, service: str, message: str, exception_type: str):
        super().__init__(service, message)
        self.exception_type = exception_type


class SerializationError(AnyCallError):
    """JSON encode/decode or type mismatch error."""
    pass


class JSONDecodeError(SerializationError):
    """Response is not valid JSON."""
    pass
