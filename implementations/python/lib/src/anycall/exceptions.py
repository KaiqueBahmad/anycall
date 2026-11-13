class AnyCallError(Exception):
    """Base exception for all AnyCall framework errors."""

    def __init__(self, service: str, message: str):
        self.service = service
        self.message = message
        super().__init__(message)


class PublishError(AnyCallError):
    """Communication/infrastructure error."""
    pass


class TimeoutError(PublishError):
    """Worker did not respond within time limit."""

    def __init__(self, service: str, message: str, call_id: str):
        super().__init__(service, message)
        self.call_id = call_id

    def get_id(self) -> str:
        return self.call_id


class QueueFullError(PublishError):
    """Raised when a call is rejected at submission because the target method's
    request queue already has at least max_queue_depth requests waiting.

    Thrown before the request is published (before LPUSH), so nothing is
    queued and the caller learns at once.

    The depth check (LLEN then LPUSH) is advisory, not a hard bound: another
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


class NoServerAvailableError(PublishError):
    """Raised when a call is rejected at submission because no server has
    heartbeated recently enough to be considered alive.

    Thrown before the request is published (before LPUSH), mirroring what a
    connection-refused error would look like over plain HTTP: fail
    immediately instead of queueing a request that may sit unread for the
    full call timeout.

    This check is advisory, not a guarantee: it only confirms that at least
    one server process is heartbeating, not that any of them support the
    requested method. A server could also heartbeat for the first time, or
    stop heartbeating, in the moment between this check and the LPUSH.
    """

    def __init__(self, method_name: str):
        super().__init__(
            "AnyCall",
            f"No server is currently alive to handle method: {method_name}",
        )
        self.method_name = method_name


class ServerLostError(PublishError):
    """Raised when the server processing a call stopped heartbeating before
    it responded, so no response will ever come.

    Detected by another live server (heartbeat reaping), about 8-10s after
    the server went quiet, or with none left, by the waiting client itself
    (waiter-driven reaping) 8-18s after. The request had started and may have partially
    run; it is not retried. Not seeing this error does not mean the server is
    alive: a server lost within the last few seconds of a call's timeout
    still surfaces as a TimeoutError.
    """

    def __init__(self, service: str, message: str, call_id: str, server_id: str):
        super().__init__(service, message)
        self.call_id = call_id
        self.server_id = server_id

    def get_id(self) -> str:
        return self.call_id


class BrokerError(PublishError):
    """Raised when a Redis command fails during a call: the connection
    dropped, Redis restarted or stopped answering.

    `published` says whether the request may have left: False when Redis
    failed before the LPUSH, so the method certainly didn't run and the call
    can be made again; True from the LPUSH on, so the method may have run,
    as with ServerLostError. The redis-py exception is the `__cause__`.
    """

    def __init__(self, service: str, message: str, call_id: str, published: bool):
        super().__init__(service, message)
        self.call_id = call_id
        self.published = published

    def get_id(self) -> str:
        return self.call_id


class RemoteExecutionError(AnyCallError):
    """Function was executed but failed on worker."""
    pass


class RemoteException(RemoteExecutionError):
    """The remote method raised an error."""

    def __init__(self, service: str, message: str, exception_type: str):
        super().__init__(service, message)
        self.exception_type = exception_type


class SerializationError(AnyCallError):
    """JSON encode/decode or type mismatch error."""
    pass


class JSONDecodeError(SerializationError):
    """Response is not valid JSON."""
    pass
