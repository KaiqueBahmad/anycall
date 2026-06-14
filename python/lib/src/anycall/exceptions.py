class RecoverableCall:
    """Interface for recoverable call errors."""

    def get_id(self) -> str:
        """Returns the call_id of the pending request."""
        raise NotImplementedError

    def get_ttl_timestamp(self) -> int:
        """Returns UNIX timestamp when result expires in broker."""
        raise NotImplementedError


class AnyCallError(Exception):
    """Base exception for all AnyCall framework errors."""

    def __init__(self, service: str, message: str):
        self.service = service
        self.message = message
        super().__init__(message)


class ChannelError(AnyCallError):
    """Communication/infrastructure error."""
    pass


class ConnectionError(ChannelError):
    """Failed to connect to broker."""
    pass


class TimeoutError(ChannelError, RecoverableCall):
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


class WorkerUnavailableError(ChannelError, RecoverableCall):
    """No worker registered for this function."""

    def __init__(self, service: str, message: str, call_id: str, ttl_timestamp: int):
        super().__init__(service, message)
        self.call_id = call_id
        self.ttl_timestamp = ttl_timestamp

    def get_id(self) -> str:
        return self.call_id

    def get_ttl_timestamp(self) -> int:
        return self.ttl_timestamp


class ChannelClosedError(ChannelError, RecoverableCall):
    """Channel was closed before receiving response."""

    def __init__(self, service: str, message: str, reason: str, call_id: str, ttl_timestamp: int):
        super().__init__(service, message)
        self.reason = reason
        self.call_id = call_id
        self.ttl_timestamp = ttl_timestamp

    def get_id(self) -> str:
        return self.call_id

    def get_ttl_timestamp(self) -> int:
        return self.ttl_timestamp


class RemoteExecutionError(AnyCallError):
    """Function was executed but failed on worker."""
    pass


class ValidationError(RemoteExecutionError):
    """Invalid input - expected logic error."""
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


class TypeMismatchError(SerializationError):
    """Returned type does not match expected type."""

    def __init__(
        self,
        service: str,
        message: str,
        expected_type: str,
        actual_type: str,
        raw_json: str,
    ):
        super().__init__(service, message)
        self.expected_type = expected_type
        self.actual_type = actual_type
        self.raw_json = raw_json
