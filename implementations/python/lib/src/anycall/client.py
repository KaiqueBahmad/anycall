from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from typing import Any, Type, TypeVar

from . import queues
from .config import AnycallProperties
from .exceptions import (
    AnyCallError,
    TimeoutError,
    RemoteException,
    SerializationError,
    JSONDecodeError,
    QueueFullError,
)
from .model import AnyCallRequest, AnyCallResponse
from .redis_adapter import RedisStreamPort
from .registry import TypeRegistry
from .serialization import deserialize, serialize

logger = logging.getLogger(__name__)

T = TypeVar("T")


class AnyCallClient(ABC):
    """Interface for RPC client."""

    @abstractmethod
    def call(
        self,
        method_name: str,
        request: Any,
        response_type: Type[T] | None = None,
        max_queue_depth: int | None = None,
    ) -> T | dict:
        """Call a remote method with explicit type (typed raia).

        Overloaded behavior:
        - call(op, req, Type) → deserialize to Type
        - call(op, req) → resolve Type from registry, raise if absent

        Args:
            method_name: Operation name
            request: Request object (will be serialized to JSON)
            response_type: Expected response type. If None, resolves from registry.
            max_queue_depth: Reject with QueueFullError if the method's request
                stream is already at or above this depth. Overrides the client's
                default_max_queue_depth for this call only. None means unbounded.

        Returns:
            Deserialized response object matching response_type

        Raises:
            QueueFullError: If the request queue is already full
            AnyCallError: On timeout, remote error, or missing type in registry
        """
        pass

    @abstractmethod
    def raw_call(self, method_name: str, request: Any, max_queue_depth: int | None = None) -> dict:
        """Call a remote method, returning raw dict (raw raia).

        Never resolves from registry; always returns native dict structure.
        Use when you want data without a model.

        Args:
            method_name: Operation name
            request: Request object (will be serialized to JSON)
            max_queue_depth: Reject with QueueFullError if the method's request
                stream is already at or above this depth. Overrides the client's
                default_max_queue_depth for this call only. None means unbounded.

        Returns:
            Raw dict (native Python structure)

        Raises:
            QueueFullError: If the request queue is already full
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

    @abstractmethod
    def get_queue_depth(self, method_name: str) -> int:
        """Read the current backlog of a method's request stream (XLEN).

        Read-only and non-destructive; safe to poll as a health gauge. Workers
        XDEL each request once it's been processed, so this reflects the true
        in-flight backlog, not the method's lifetime call count.

        Args:
            method_name: Operation name

        Returns:
            Number of entries currently in the method's request stream
        """
        pass

    @abstractmethod
    def set_default_max_queue_depth(self, max_queue_depth: int | None) -> None:
        """Change the default max_queue_depth applied to calls that don't pass
        a per-call override. Takes effect immediately for subsequent calls;
        in-flight calls are unaffected.

        Args:
            max_queue_depth: New default backlog limit, or None to make calls
                unbounded again
        """
        pass

    @abstractmethod
    def get_default_max_queue_depth(self) -> int | None:
        """Return the client's current default max_queue_depth, or None if
        calls are unbounded by default."""
        pass


class AnyCallClientImpl(AnyCallClient):
    """RPC client implementation."""

    def __init__(
        self,
        redis_adapter: RedisStreamPort,
        props: AnycallProperties,
        default_max_queue_depth: int | None = None,
    ):
        self.redis = redis_adapter
        self.props = props
        self._registry = TypeRegistry()
        self._default_max_queue_depth = default_max_queue_depth

    def call(
        self,
        method_name: str,
        request: Any,
        response_type: Type[T] | None = None,
        max_queue_depth: int | None = None,
    ) -> T | dict:
        """Call a remote method with explicit or registry-resolved type (typed raia).

        Args:
            method_name: Operation name
            request: Request object (will be serialized to JSON)
            response_type: Expected response type. If None, resolves from registry.
            max_queue_depth: Per-call override for the client's default_max_queue_depth.

        Returns:
            Deserialized response object

        Raises:
            QueueFullError: If the request queue is already full
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

        return self._call_impl(method_name, request, resolved_type, max_queue_depth)

    def raw_call(self, method_name: str, request: Any, max_queue_depth: int | None = None) -> dict:
        """Call a remote method, returning raw dict (raw raia).

        Never resolves from registry; always returns native dict structure.

        Args:
            method_name: Operation name
            request: Request object (will be serialized to JSON)
            max_queue_depth: Per-call override for the client's default_max_queue_depth.

        Returns:
            Raw dict (native Python structure)

        Raises:
            QueueFullError: If the request queue is already full
            AnyCallError: On timeout or remote error
        """
        return self._call_impl(method_name, request, dict, max_queue_depth)

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

    def get_queue_depth(self, method_name: str) -> int:
        """Read the current backlog of a method's request stream (XLEN)."""
        return self.redis.length(queues.request_queue(method_name))

    def set_default_max_queue_depth(self, max_queue_depth: int | None) -> None:
        """Change the default max_queue_depth applied to future calls."""
        self._default_max_queue_depth = max_queue_depth

    def get_default_max_queue_depth(self) -> int | None:
        """Return the client's current default max_queue_depth."""
        return self._default_max_queue_depth

    def _call_impl(
        self,
        method_name: str,
        request: Any,
        response_type: Type,
        max_queue_depth: int | None = None,
    ) -> Any:
        """Internal implementation of call (both typed and raw).

        Args:
            method_name: Operation name
            request: Request object
            response_type: Type to deserialize to (never None)
            max_queue_depth: Per-call override for the client's default_max_queue_depth.

        Returns:
            Deserialized response

        Raises:
            QueueFullError: If the request queue is already full
            AnyCallError: On timeout or remote error
        """
        effective_max_queue_depth = (
            max_queue_depth if max_queue_depth is not None else self._default_max_queue_depth
        )

        try:
            payload = serialize(request)
        except (TypeError, ValueError) as e:
            raise SerializationError(method_name, f"Failed to serialize request: {e}")
        rpc_request = AnyCallRequest.create(method_name, payload)

        request_stream = queues.request_queue(method_name)
        response_stream = queues.response_queue(rpc_request.request_id)

        if effective_max_queue_depth is not None:
            queue_depth = self.redis.length(request_stream)
            if queue_depth >= effective_max_queue_depth:
                raise QueueFullError(method_name, queue_depth, effective_max_queue_depth)

        try:
            try:
                request_json = serialize(rpc_request)
            except (TypeError, ValueError) as e:
                raise SerializationError(method_name, f"Failed to serialize RPC request: {e}")
            self.redis.add(request_stream, {"data": request_json})

            timeout_ms = int(self.props.timeout.total_seconds() * 1000)
            result = self.redis.read(response_stream, timeout_ms)

            if result is None:
                raise TimeoutError(
                    method_name,
                    f"Timeout waiting for response from method: {method_name}",
                    timeout_ms,
                    rpc_request.request_id,
                    int((self.props.timeout.total_seconds() + 60) * 1000),
                )

            _, messages = result[0]
            _, message_data = messages[0]
            response_json = message_data[b"data"].decode("utf-8")
            try:
                response = deserialize(response_json, AnyCallResponse)
            except json.JSONDecodeError as e:
                raise JSONDecodeError(method_name, f"Failed to decode response: {e}")

            if response.has_error():
                raise RemoteException(method_name, response.error_msg or "Unknown error", "RemoteExecutionError")

            payload = response.payload
            if payload is None:
                raise SerializationError(method_name, "Response payload is missing")
            try:
                return deserialize(payload, response_type)
            except json.JSONDecodeError as e:
                raise JSONDecodeError(method_name, f"Failed to decode response payload: {e}")

        finally:
            self.redis.delete(response_stream)
