import logging
from abc import ABC, abstractmethod
from typing import Any, Type, TypeVar

from . import queues
from .config import AnycallProperties
from .exceptions import AnyCallError
from .model import AnyCallRequest, AnyCallResponse
from .redis_adapter import RedisStreamAdapter
from .registry import TypeRegistry
from .serialization import deserialize, serialize

logger = logging.getLogger(__name__)

T = TypeVar("T")


class AnyCallClient(ABC):
    """Interface for RPC client."""

    @abstractmethod
    def call(self, method_name: str, request: Any, response_type: Type[T] | None = None) -> T | dict:
        """Call a remote method with explicit type (typed raia).

        Overloaded behavior:
        - call(op, req, Type) → deserialize to Type
        - call(op, req) → resolve Type from registry, raise if absent

        Args:
            method_name: Operation name
            request: Request object (will be serialized to JSON)
            response_type: Expected response type. If None, resolves from registry.

        Returns:
            Deserialized response object matching response_type

        Raises:
            AnyCallError: On timeout, remote error, or missing type in registry
        """
        pass

    @abstractmethod
    def call_raw(self, method_name: str, request: Any) -> dict:
        """Call a remote method, returning raw dict (raw raia).

        Never resolves from registry; always returns native dict structure.
        Use when you want data without a model.

        Args:
            method_name: Operation name
            request: Request object (will be serialized to JSON)

        Returns:
            Raw dict (native Python structure)

        Raises:
            AnyCallError: On timeout or remote error
        """
        pass

    @abstractmethod
    def register_type(self, operation: str, response_type: Type) -> None:
        """Register response type for an operation.

        Write-once semantics:
        - First registration succeeds
        - Re-registering with SAME type is idempotent (no-op)
        - Re-registering with DIFFERENT type raises AnyCallError

        Args:
            operation: Operation name
            response_type: Response type for deserialization

        Raises:
            AnyCallError: If operation already registered with different type
        """
        pass


class AnyCallClientImpl(AnyCallClient):
    """RPC client implementation."""

    def __init__(self, redis_adapter: RedisStreamAdapter, props: AnycallProperties):
        self.redis = redis_adapter
        self.props = props
        self._registry = TypeRegistry()

    def call(self, method_name: str, request: Any, response_type: Type[T] | None = None) -> T | dict:
        """Call a remote method with explicit or registry-resolved type (typed raia).

        Args:
            method_name: Operation name
            request: Request object (will be serialized to JSON)
            response_type: Expected response type. If None, resolves from registry.

        Returns:
            Deserialized response object

        Raises:
            AnyCallError: On timeout, remote error, or missing type in registry
        """
        resolved_type = response_type
        if resolved_type is None:
            resolved_type = self._registry.get(method_name)
            if resolved_type is None:
                raise AnyCallError(
                    "unknown",
                    f"No response type registered for operation '{method_name}'. "
                    f"Either call with explicit type: call('{method_name}', req, YourType), "
                    f"or register the type first: register_type('{method_name}', YourType)."
                )

        return self._call_impl(method_name, request, resolved_type)

    def call_raw(self, method_name: str, request: Any) -> dict:
        """Call a remote method, returning raw dict (raw raia).

        Never resolves from registry; always returns native dict structure.

        Args:
            method_name: Operation name
            request: Request object (will be serialized to JSON)

        Returns:
            Raw dict (native Python structure)

        Raises:
            AnyCallError: On timeout or remote error
        """
        return self._call_impl(method_name, request, dict)

    def register_type(self, operation: str, response_type: Type) -> None:
        """Register response type for an operation.

        Write-once semantics: first registration succeeds, re-registering with
        same type is idempotent, re-registering with different type raises error.

        Args:
            operation: Operation name
            response_type: Response type for deserialization

        Raises:
            AnyCallError: If operation already registered with different type
        """
        self._registry.register(operation, response_type)

    def _call_impl(self, method_name: str, request: Any, response_type: Type) -> Any:
        """Internal implementation of call (both typed and raw).

        Args:
            method_name: Operation name
            request: Request object
            response_type: Type to deserialize to (never None)

        Returns:
            Deserialized response

        Raises:
            AnyCallError: On timeout or remote error
        """
        payload = serialize(request)
        rpc_request = AnyCallRequest.create(method_name, payload)

        request_stream = queues.request_queue(method_name)
        response_stream = queues.response_queue(rpc_request.request_id)

        try:
            request_json = serialize(rpc_request)
            self.redis.add(request_stream, {"data": request_json})

            timeout_ms = int(self.props.timeout.total_seconds() * 1000)
            result = self.redis.read(response_stream, timeout_ms)

            if result is None:
                raise AnyCallError(
                    "unknown",
                    f"Timeout waiting for response from method: {method_name}"
                )

            stream_name, messages = result[0]
            message_id, message_data = messages[0]
            response_json = message_data[b"data"].decode("utf-8")
            response = deserialize(response_json, AnyCallResponse)

            if response.has_error():
                raise AnyCallError("unknown", f"Error from remote method: {response.error_msg}")

            return deserialize(response.payload, response_type)

        finally:
            self.redis.delete(response_stream)
