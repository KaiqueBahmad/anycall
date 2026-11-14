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
from typing import Any, Callable, Optional, Type, TypeVar

import dacite
import redis.exceptions

from . import queues
from .exceptions import (
    AnyCallError,
    BrokerError,
    ClientClosedError,
    NoServerAvailableError,
    QueueFullError,
    RemoteException,
    ServerLostError,
    SerializationError,
    TimeoutError,
)
from .model import AnyCallRequest, AnyCallResponse, read_response_request_id
from .options import DEFAULT_CALL_OPTIONS, CallOptions
from .queues import Queues
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
        options: CallOptions = DEFAULT_CALL_OPTIONS,
    ) -> T | dict:
        """Call a remote method with explicit type (typed call).

        Overloaded behavior:
        - call(op, req, Type) → deserialize to Type
        - call(op, req) → resolve Type from registry, raise if absent

        Args:
            method_name: Operation name
            request: Request object (will be serialized to JSON)
            response_type: Expected response type. If None, resolves from registry.
            options: This call's timeout and queue limit; a setting left
                out keeps the client's. See CallOptions

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
    def raw_call(self, method_name: str, request: Any, options: CallOptions = DEFAULT_CALL_OPTIONS) -> dict:
        """Call a remote method, returning raw dict (raw call).

        Never resolves from registry; always returns native dict structure.
        Use when you want data without a model.

        Args:
            method_name: Operation name
            request: Request object (will be serialized to JSON)
            options: This call's timeout and queue limit; a setting left
                out keeps the client's. See CallOptions

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
    def queue_depth(self, method_name: str) -> int:
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

    @property
    @abstractmethod
    def defaults(self) -> CallOptions:
        """The settings every call takes unless its own options replace
        them, both set: a timeout or None, a queue limit or None."""
        pass

    @abstractmethod
    def update_defaults(self, options: CallOptions) -> None:
        """Change the client's defaults for calls made from now on; calls
        already waiting keep theirs. What `options` set replaces the
        client's, and what they leave out stays as it is:

            client.update_defaults(CallOptions(max_queue_depth=200))  # only the queue limit

        Safe to call from any thread.
        """
        pass

    @abstractmethod
    def close(self) -> None:
        """Close the client at once: calls still waiting fail with
        ClientClosedError, as does any call made after, and the client's
        connections and reader thread are gone when this returns. A request
        already published may still be processed by a server; its response
        is dropped. Closing again does nothing."""
        pass

    def __enter__(self) -> "AnyCallClient":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

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
    `<prefix>:responses:<client id>`. A single reader thread blocks on it and
    hands each response to the call waiting for it, by its requestId, so any
    number of calls can wait at once without a connection each: a sync call
    waits on its future, an async one (see `aio`) awaits it.
    """

    def __init__(
        self,
        redis_adapter: RedisQueuePort,
        defaults: CallOptions = DEFAULT_CALL_OPTIONS,
        keys: Queues = queues.DEFAULT,
    ):
        """
        Args:
            redis_adapter: Redis queue adapter
            defaults: The settings of every call; a setting left out means no
                limit, and a call's own CallOptions replace them
            keys: The keys this client publishes to and reads from
        """
        self._keys = keys
        self.redis = redis_adapter
        # Every call's settings, unless the call's own options replace them;
        # None means no limit. Each is read once per call; update_defaults
        # may change them at any time.
        self._timeout: Optional[timedelta] = None
        self._max_queue_depth: Optional[int] = None
        self.update_defaults(defaults)
        self._registry = TypeRegistry()
        self._client_id = str(uuid.uuid4())
        self._response_queue = keys.response_queue(self._client_id)
        self._pending: dict[str, _Pending] = {}
        self._lock = threading.Lock()
        self._reader: Optional[threading.Thread] = None
        self._closed = False
        self._aio = AsyncCalls(self)

    @property
    def client_id(self) -> str:
        """This client's id: its response queue is `<prefix>:responses:<id>`."""
        return self._client_id

    @property
    def aio(self) -> "AsyncCalls":
        return self._aio

    def call(
        self,
        method_name: str,
        request: Any,
        response_type: Type[T] | None = None,
        options: CallOptions = DEFAULT_CALL_OPTIONS,
    ) -> T | dict:
        """Call a remote method with explicit or registry-resolved type (typed call).

        Args:
            method_name: Operation name
            request: Request object (will be serialized to JSON)
            response_type: Expected response type. If None, resolves from registry.
            options: This call's timeout and queue limit; a setting left
                out keeps the client's. See CallOptions

        Returns:
            Deserialized response object

        Raises:
            QueueFullError: If the request queue is already full
            NoServerAvailableError: If no server is currently alive
            BrokerError: If a Redis command fails during the call
            AnyCallError: On timeout, remote error, or missing type in registry
        """
        resolved_type = self._resolve_type(method_name, response_type)
        return self._call_sync(method_name, request, resolved_type, options)

    def raw_call(self, method_name: str, request: Any, options: CallOptions = DEFAULT_CALL_OPTIONS) -> dict:
        """Call a remote method, returning raw dict (raw call).

        Never resolves from registry; always returns native dict structure.

        Args:
            method_name: Operation name
            request: Request object (will be serialized to JSON)
            options: This call's timeout and queue limit; a setting left
                out keeps the client's. See CallOptions

        Returns:
            Raw dict (native Python structure)

        Raises:
            QueueFullError: If the request queue is already full
            NoServerAvailableError: If no server is currently alive
            BrokerError: If a Redis command fails during the call
            AnyCallError: On timeout or remote error
        """
        return self._call_sync(method_name, request, dict, options)

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

    @property
    def defaults(self) -> CallOptions:
        """A snapshot of the client's defaults, both set."""
        return CallOptions(timeout=self._timeout, max_queue_depth=self._max_queue_depth)

    def update_defaults(self, options: CallOptions) -> None:
        """Change the client's defaults for calls made from now on; what
        `options` set replaces the client's, what they leave out stays."""
        self._timeout = options.timeout_or(self._timeout)
        self._max_queue_depth = options.max_queue_depth_or(self._max_queue_depth)

    def queue_depth(self, method_name: str) -> int:
        """Read the current backlog of a method's request queue (LLEN)."""
        if self._closed:
            raise self._closed_error(method_name)
        return self.redis.length(self._keys.request_queue(method_name))

    def close(self) -> None:
        """Close the client at once. Calls still waiting fail with
        ClientClosedError, and so does any call made after. Closing the
        Redis connection ends the reader's BRPOP at once, and the reader is
        gone when this returns."""
        with self._lock:
            if self._closed:
                return
            self._closed = True
            reader = self._reader
        self._fail_all(lambda request_id, method_name: ClientClosedError(
            method_name, "The client was closed while the call was waiting"))
        try:
            self.redis.close()
        except Exception as e:
            logger.debug(f"Failed to close the Redis connection: {e}")
        if reader is not None:
            reader.join(WAITER_REAP_SLICE_SECONDS)

    @staticmethod
    def _closed_error(method_name: str) -> ClientClosedError:
        return ClientClosedError(method_name, f"The client is closed: method {method_name} was not called")

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

    def _timeout_seconds(self, options: CallOptions) -> Optional[float]:
        """The call's timeout in seconds: its options', or the client's;
        None waits with no limit."""
        timeout = options.timeout_or(self._timeout)
        return None if timeout is None else timeout.total_seconds()

    def _call_sync(self, method_name: str, request: Any, response_type: Type, options: CallOptions) -> Any:
        request_id, future = self._publish(method_name, request, options)
        try:
            response_json = future.result(self._timeout_seconds(options))
        except concurrent.futures.TimeoutError:
            self._forget(request_id)
            raise self._timed_out(method_name, request_id) from None
        return self._outcome(method_name, request_id, response_json, response_type)

    def _publish(
        self, method_name: str, request: Any, options: CallOptions
    ) -> tuple[str, concurrent.futures.Future]:
        """Check, then publish a call, and return its request id and the
        future its response will complete. The future is in place before
        the LPUSH, so the response can't arrive before anyone waits for it.

        Raises:
            SerializationError: If the request can't be serialized
            NoServerAvailableError: If no server is currently alive
            QueueFullError: If the request queue is already full
            BrokerError: If a Redis command fails
            ClientClosedError: If the client is closed
        """
        if self._closed:
            raise self._closed_error(method_name)
        effective_max_queue_depth = options.max_queue_depth_or(self._max_queue_depth)
        try:
            payload = serialize(request)
        except (TypeError, ValueError) as e:
            raise SerializationError(method_name, f"Failed to serialize request: {e}")
        rpc_request = AnyCallRequest.create(method_name, payload, self._client_id)
        request_queue = self._keys.request_queue(method_name)

        try:
            if self.redis.alive_count(self._keys.heartbeat_key, queues.HEARTBEAT_TTL_SECONDS) == 0:
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
            # Checked under the lock close() sets it under: a call that gets
            # past this is failed by close(), one that doesn't is refused.
            if self._closed:
                raise self._closed_error(method_name)
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
            except Exception as e:
                if self._closed:
                    # close() closed the connection under the BRPOP.
                    return
                if not isinstance(e, redis.exceptions.RedisError):
                    raise
                self._fail_all(lambda request_id, method_name, error=e: self._broker_error(
                    request_id, method_name, error))
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

    def _fail_all(self, error_for: Callable[[str, str], AnyCallError]) -> None:
        """Fail every waiting call, with the error `error_for` makes from its
        request id and method."""
        with self._lock:
            pending, self._pending = self._pending, {}
        for request_id, call in pending.items():
            if not call.future.done():
                call.future.set_exception(error_for(request_id, call.method_name))

    @staticmethod
    def _broker_error(request_id: str, method_name: str, error: Exception) -> BrokerError:
        broker_error = BrokerError(
            method_name,
            f"Redis failed after the request may have been published: {error}",
            request_id,
            published=True,
        )
        broker_error.__cause__ = error
        return broker_error

    def _reap(self) -> None:
        """Fail back the requests of every server that stopped heartbeating,
        the same work a server does on its heartbeat. Costs one script call
        when no server is dead. Failures only log: the reader goes back to
        reading either way."""
        try:
            dead = self.redis.stale_members(self._keys.heartbeat_key, queues.HEARTBEAT_TTL_SECONDS)
            reap_dead_servers(self.redis, self._keys, dead)
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
        options: CallOptions = DEFAULT_CALL_OPTIONS,
    ) -> T | dict:
        """`AnyCallClient.call`, to await."""
        resolved_type = self._client._resolve_type(method_name, response_type)
        return await self._call(method_name, request, resolved_type, options)

    async def raw_call(self, method_name: str, request: Any, options: CallOptions = DEFAULT_CALL_OPTIONS) -> dict:
        """`AnyCallClient.raw_call`, to await."""
        return await self._call(method_name, request, dict, options)

    async def _call(self, method_name: str, request: Any, response_type: Type, options: CallOptions) -> Any:
        client = self._client
        loop = asyncio.get_running_loop()
        request_id, future = await loop.run_in_executor(
            None, client._publish, method_name, request, options
        )
        try:
            response_json = await asyncio.wait_for(asyncio.wrap_future(future), client._timeout_seconds(options))
        except asyncio.TimeoutError:
            client._forget(request_id)
            raise client._timed_out(method_name, request_id) from None
        return client._outcome(method_name, request_id, response_json, response_type)
