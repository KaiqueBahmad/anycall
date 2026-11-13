from __future__ import annotations

import json
import logging
import time
from abc import ABC, abstractmethod
from datetime import timedelta
from typing import Any, Type, TypeVar

import dacite
import redis.exceptions

from . import queues
from .exceptions import (
    AnyCallError,
    BrokerError,
    JSONDecodeError,
    NoServerAvailableError,
    QueueFullError,
    RemoteException,
    ServerLostError,
    SerializationError,
    TimeoutError,
)
from .model import AnyCallRequest, AnyCallResponse
from .reaping import reap_dead_servers
from .redis_adapter import RedisQueuePort
from .registry import TypeRegistry
from .serialization import deserialize, serialize

logger = logging.getLogger(__name__)

# A call waits for its response in slices of at most this long; after each
# one that ends empty, it reaps dead servers itself (see `reaping`), so its
# request is failed back even with no server left alive to do it.
WAITER_REAP_SLICE_SECONDS = 10

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
                queue is already at or above this depth. Overrides the client's
                default_max_queue_depth for this call only. None means unbounded.

        Returns:
            Deserialized response object matching response_type

        Raises:
            QueueFullError: If the request queue is already full
            NoServerAvailableError: If no server is currently alive
            BrokerError: If a Redis command fails during the call
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
                queue is already at or above this depth. Overrides the client's
                default_max_queue_depth for this call only. None means unbounded.

        Returns:
            Raw dict (native Python structure)

        Raises:
            QueueFullError: If the request queue is already full
            NoServerAvailableError: If no server is currently alive
            BrokerError: If a Redis command fails during the call
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
        """Read the current backlog of a method's request queue (LLEN).

        Read-only and non-destructive; safe to poll as a health gauge. A
        request leaves the queue as soon as a server takes it, so this counts
        only requests still waiting, not the ones being processed.

        Args:
            method_name: Operation name

        Returns:
            Number of requests currently waiting in the method's queue
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
        redis_adapter: RedisQueuePort,
        timeout: timedelta = timedelta(0),
        default_max_queue_depth: int | None = None,
    ):
        """
        Args:
            redis_adapter: Redis queue adapter
            timeout: How long a call waits for its response; timedelta(0)
                waits with no limit
            default_max_queue_depth: Default backlog limit for every call;
                None means unbounded
        """
        self.redis = redis_adapter
        self._timeout = timeout
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
            NoServerAvailableError: If no server is currently alive
            BrokerError: If a Redis command fails during the call
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
            NoServerAvailableError: If no server is currently alive
            BrokerError: If a Redis command fails during the call
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
        """Read the current backlog of a method's request queue (LLEN)."""
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
            NoServerAvailableError: If no server is currently alive
            BrokerError: If a Redis command fails during the call
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

        request_queue = queues.request_queue(method_name)
        response_queue = queues.response_queue(rpc_request.request_id)

        try:
            if self.redis.alive_count(queues.HEARTBEAT_KEY, queues.HEARTBEAT_TTL_SECONDS) == 0:
                raise NoServerAvailableError(method_name)

            if effective_max_queue_depth is not None:
                queue_depth = self.redis.length(request_queue)
                if queue_depth >= effective_max_queue_depth:
                    raise QueueFullError(method_name, queue_depth, effective_max_queue_depth)
        except redis.exceptions.RedisError as e:
            raise BrokerError(
                method_name,
                f"Redis failed before the request was published: {e}",
                rpc_request.request_id,
                published=False,
            ) from e

        redis_failed = False
        try:
            try:
                request_json = serialize(rpc_request)
            except (TypeError, ValueError) as e:
                raise SerializationError(method_name, f"Failed to serialize RPC request: {e}")
            try:
                self.redis.push(request_queue, request_json)
                response_json = self._await_response(response_queue)
            except redis.exceptions.RedisError as e:
                redis_failed = True
                # The LPUSH may have reached Redis before the connection dropped.
                raise BrokerError(
                    method_name,
                    f"Redis failed after the request may have been published: {e}",
                    rpc_request.request_id,
                    published=True,
                ) from e

            if response_json is None:
                raise TimeoutError(
                    method_name,
                    f"Timeout waiting for response from method: {method_name}",
                    rpc_request.request_id,
                )

            try:
                response = deserialize(response_json, AnyCallResponse)
            except json.JSONDecodeError as e:
                raise JSONDecodeError(method_name, f"Failed to decode response: {e}")
            except TypeError as e:
                raise SerializationError(method_name, f"Invalid response: {e}")

            if response.lost_server is not None:
                raise ServerLostError(
                    method_name,
                    response.error_msg or f"server {response.lost_server} was lost",
                    rpc_request.request_id,
                    response.lost_server,
                )
            if response.has_error():
                raise RemoteException(method_name, response.error_msg or "Unknown error", "RemoteExecutionError")

            # A method that returned None sends the payload "null"; a null
            # payload without an error is a broken response, not a None result.
            payload = response.payload
            if payload is None:
                raise SerializationError(
                    method_name,
                    f"Response from method {method_name} has neither a payload nor an error; "
                    f"the method may have run",
                )
            try:
                return deserialize(payload, response_type)
            except json.JSONDecodeError as e:
                raise JSONDecodeError(method_name, f"Failed to decode response payload: {e}")
            except dacite.DaciteError as e:
                raise SerializationError(method_name, f"Response payload doesn't fit {response_type.__name__}: {e}")

        finally:
            # After a Redis failure the DEL would only wait out the socket timeout
            # again. Nothing is lost: a response queue only exists once a response
            # is written, and every write sets its RESPONSE_TTL.
            if not redis_failed:
                try:
                    self.redis.delete(response_queue)
                except redis.exceptions.RedisError:
                    pass  # never hide the call's own outcome

    def _await_response(self, response_queue: str) -> str | None:
        """Wait for the call's response, up to the client's timeout (forever
        if it's zero), in slices of WAITER_REAP_SLICE_SECONDS. Returns None
        once the timeout is up.

        A slice that ends empty reaps dead servers (see `_reap`), so a request
        whose server died is failed back even when no other server is alive
        to notice.
        """
        timeout_seconds = self._timeout.total_seconds()
        deadline = time.monotonic() + timeout_seconds if timeout_seconds > 0 else None
        while True:
            wait = WAITER_REAP_SLICE_SECONDS
            if deadline is not None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return None
                # BRPOP takes 0 as "forever", so never let a slice round down to it.
                wait = max(min(wait, remaining), 0.001)
            result = self.redis.pop([response_queue], wait)
            if result is not None:
                return result[1]
            self._reap()

    def _reap(self) -> None:
        """Fail back the requests of every server that stopped heartbeating,
        the same work a server does on its heartbeat. Costs one script call
        when no server is dead. Failures only log: the call goes back to
        waiting either way."""
        try:
            dead = self.redis.stale_members(queues.HEARTBEAT_KEY, queues.HEARTBEAT_TTL_SECONDS)
            reap_dead_servers(self.redis, dead)
        except Exception as e:
            logger.warning(f"Failed to reap dead servers: {e}")
