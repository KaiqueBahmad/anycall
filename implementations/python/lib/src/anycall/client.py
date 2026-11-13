from __future__ import annotations

import asyncio
import concurrent.futures
import json
import logging
import threading
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Optional, Type, TypeVar

import dacite
import redis.exceptions

from . import queues
from .exceptions import (
    AnyCallError,
    BrokerError,
    NoServerAvailableError,
    QueueFullError,
    RemoteException,
    ServerLostError,
    SerializationError,
    TimeoutError,
)
from .model import AnyCallRequest, AnyCallResponse, read_response_request_id
from .reaping import reap_dead_servers
from .redis_adapter import RedisQueuePort
from .registry import TypeRegistry
from .serialization import deserialize, serialize

logger = logging.getLogger(__name__)

# A client reads its response queue in slices of at most this long; after each
# one that ends empty while calls are waiting, it reaps dead servers itself
# (see `reaping`), so their requests are failed back even with no server left
# alive to do it.
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

    @property
    @abstractmethod
    def aio(self) -> "AsyncCalls":
        """The same calls, to `await`: `await client.aio.call(...)`. They share
        this client's response queue, registered types and settings."""
        pass


@dataclass
class _Pending:
    """A call waiting for its response, until the reader hands it over."""
    method_name: str
    future: concurrent.futures.Future


class AnyCallClientImpl(AnyCallClient):
    """RPC client implementation.

    Every response to this client's calls goes to one queue of its own,
    `anycall:responses:<client id>`. A single reader thread blocks on it and
    hands each response to the call waiting for it, by its requestId, so any
    number of calls can wait at once without a connection each: a sync call
    waits on its future, an async one (see `aio`) awaits it.
    """

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
        self._client_id = str(uuid.uuid4())
        self._response_queue = queues.response_queue(self._client_id)
        self._pending: dict[str, _Pending] = {}
        self._lock = threading.Lock()
        self._reader: Optional[threading.Thread] = None
        self._closed = False
        self._aio = AsyncCalls(self)

    @property
    def client_id(self) -> str:
        """This client's id: its response queue is `anycall:responses:<id>`."""
        return self._client_id

    @property
    def aio(self) -> "AsyncCalls":
        return self._aio

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
        resolved_type = self._resolve_type(method_name, response_type)
        return self._call_sync(method_name, request, resolved_type, max_queue_depth)

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
        return self._call_sync(method_name, request, dict, max_queue_depth)

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

    def close(self) -> None:
        """Stop reading responses. Calls still waiting fail when their
        timeout is up (or never, with no timeout); make no calls after."""
        self._closed = True

    def _resolve_type(self, method_name: str, response_type: Type | None) -> Type:
        if response_type is not None:
            return response_type
        resolved = self._registry.get(method_name)
        if resolved is None:
            raise AnyCallError(
                "unknown",
                f"No response type registered for operation '{method_name}'. "
                f"Either call with explicit type: call('{method_name}', req, YourType), "
                f"or register the type first: register_type('{method_name}', YourType)."
            )
        return resolved

    def _timeout_seconds(self) -> Optional[float]:
        seconds = self._timeout.total_seconds()
        return seconds if seconds > 0 else None

    def _call_sync(self, method_name: str, request: Any, response_type: Type, max_queue_depth: int | None) -> Any:
        request_id, future = self._publish(method_name, request, max_queue_depth)
        try:
            response_json = future.result(self._timeout_seconds())
        except concurrent.futures.TimeoutError:
            self._forget(request_id)
            raise self._timed_out(method_name, request_id) from None
        return self._outcome(method_name, request_id, response_json, response_type)

    def _publish(
        self, method_name: str, request: Any, max_queue_depth: int | None
    ) -> tuple[str, concurrent.futures.Future]:
        """Check, then publish a call, and return its request id and the
        future its response will complete. The future is in place before
        the LPUSH, so the response can't arrive before anyone waits for it.

        Raises:
            SerializationError: If the request can't be serialized
            NoServerAvailableError: If no server is currently alive
            QueueFullError: If the request queue is already full
            BrokerError: If a Redis command fails
        """
        effective_max_queue_depth = (
            max_queue_depth if max_queue_depth is not None else self._default_max_queue_depth
        )
        try:
            payload = serialize(request)
        except (TypeError, ValueError) as e:
            raise SerializationError(method_name, f"Failed to serialize request: {e}")
        rpc_request = AnyCallRequest.create(method_name, payload, self._client_id)
        request_queue = queues.request_queue(method_name)

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

        try:
            request_json = serialize(rpc_request)
        except (TypeError, ValueError) as e:
            raise SerializationError(method_name, f"Failed to serialize RPC request: {e}")

        future: concurrent.futures.Future = concurrent.futures.Future()
        with self._lock:
            self._pending[rpc_request.request_id] = _Pending(method_name, future)
            self._start_reader()
        try:
            self.redis.push(request_queue, request_json)
        except redis.exceptions.RedisError as e:
            self._forget(rpc_request.request_id)
            # The LPUSH may have reached Redis before the connection dropped.
            raise BrokerError(
                method_name,
                f"Redis failed after the request may have been published: {e}",
                rpc_request.request_id,
                published=True,
            ) from e
        return rpc_request.request_id, future

    def _forget(self, request_id: str) -> None:
        """Stop waiting for a call: a response that still comes is dropped."""
        with self._lock:
            self._pending.pop(request_id, None)

    @staticmethod
    def _timed_out(method_name: str, request_id: str) -> TimeoutError:
        return TimeoutError(method_name, f"Timeout waiting for response from method: {method_name}", request_id)

    def _outcome(self, method_name: str, request_id: str, response_json: str, response_type: Type) -> Any:
        """Turn the response the reader handed over into the call's result,
        or its error."""
        try:
            response = deserialize(response_json, AnyCallResponse)
        except json.JSONDecodeError as e:
            raise SerializationError(method_name, f"Failed to decode response: {e}")
        except TypeError as e:
            raise SerializationError(method_name, f"Invalid response: {e}")

        if response.lost_server is not None:
            raise ServerLostError(
                method_name,
                response.error_msg or f"server {response.lost_server} was lost",
                request_id,
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
            raise SerializationError(method_name, f"Failed to decode response payload: {e}")
        except dacite.DaciteError as e:
            raise SerializationError(method_name, f"Response payload doesn't fit {response_type.__name__}: {e}")

    def _start_reader(self) -> None:
        """Start the reader on the first call. Called under `_lock`."""
        if self._reader is None:
            self._reader = threading.Thread(target=self._read_responses, name="anycall-responses", daemon=True)
            self._reader.start()

    def _read_responses(self) -> None:
        """Read this client's response queue and hand each response to the
        call waiting for it, by its requestId, until the client closes.

        Reads in slices of WAITER_REAP_SLICE_SECONDS; after each one that ends
        empty with calls still waiting, reaps dead servers (see `_reap`). If
        Redis fails, every waiting call fails with a BrokerError, and reading
        starts over.
        """
        while not self._closed:
            try:
                result = self.redis.pop([self._response_queue], WAITER_REAP_SLICE_SECONDS)
            except redis.exceptions.RedisError as e:
                self._fail_all(e)
                threading.Event().wait(1)
                continue
            if result is None:
                with self._lock:
                    waiting = bool(self._pending)
                if waiting:
                    self._reap()
                continue
            self._hand_over(result[1])

    def _hand_over(self, response_json: str) -> None:
        request_id = read_response_request_id(response_json)
        with self._lock:
            pending = self._pending.pop(request_id, None) if request_id is not None else None
        if pending is None:
            # A late answer to a call that timed out, or one with no readable
            # requestId: there's no call to hand it to.
            logger.debug(f"Dropped a response no call is waiting for: request {request_id}")
            return
        if not pending.future.done():
            pending.future.set_result(response_json)

    def _fail_all(self, error: Exception) -> None:
        """Fail every waiting call after Redis failed under the reader."""
        with self._lock:
            pending, self._pending = self._pending, {}
        for request_id, call in pending.items():
            broker_error = BrokerError(
                call.method_name,
                f"Redis failed after the request may have been published: {error}",
                request_id,
                published=True,
            )
            broker_error.__cause__ = error
            if not call.future.done():
                call.future.set_exception(broker_error)

    def _reap(self) -> None:
        """Fail back the requests of every server that stopped heartbeating,
        the same work a server does on its heartbeat. Costs one script call
        when no server is dead. Failures only log: the reader goes back to
        reading either way."""
        try:
            dead = self.redis.stale_members(queues.HEARTBEAT_KEY, queues.HEARTBEAT_TTL_SECONDS)
            reap_dead_servers(self.redis, dead)
        except Exception as e:
            logger.warning(f"Failed to reap dead servers: {e}")


class AsyncCalls:
    """The calls of an `AnyCallClient`, to `await`: `client.aio.call(...)`.

    The same calls, with the same registered types, timeout and errors, on the
    same response queue: the client's reader completes a future, and this
    awaits it. The few Redis commands that publish a call run off the event
    loop, so it's never blocked.
    """

    def __init__(self, client: AnyCallClientImpl):
        self._client = client

    async def call(
        self,
        method_name: str,
        request: Any,
        response_type: Type[T] | None = None,
        max_queue_depth: int | None = None,
    ) -> T | dict:
        """`AnyCallClient.call`, to await."""
        resolved_type = self._client._resolve_type(method_name, response_type)
        return await self._call(method_name, request, resolved_type, max_queue_depth)

    async def raw_call(self, method_name: str, request: Any, max_queue_depth: int | None = None) -> dict:
        """`AnyCallClient.raw_call`, to await."""
        return await self._call(method_name, request, dict, max_queue_depth)

    async def _call(self, method_name: str, request: Any, response_type: Type, max_queue_depth: int | None) -> Any:
        client = self._client
        loop = asyncio.get_running_loop()
        request_id, future = await loop.run_in_executor(
            None, client._publish, method_name, request, max_queue_depth
        )
        try:
            response_json = await asyncio.wait_for(asyncio.wrap_future(future), client._timeout_seconds())
        except asyncio.TimeoutError:
            client._forget(request_id)
            raise client._timed_out(method_name, request_id) from None
        return client._outcome(method_name, request_id, response_json, response_type)
