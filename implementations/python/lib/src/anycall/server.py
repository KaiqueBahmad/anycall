import inspect
import logging
import threading
import time
import uuid
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional

from . import queues
from .config import AnycallProperties
from .context import AnycallContext
from .exceptions import AnyCallError
from .model import AnyCallRequest, AnyCallResponse
from .redis_adapter import RedisStreamAdapter
from .serialization import deserialize, serialize
from redis.exceptions import TimeoutError
logger = logging.getLogger(__name__)

POLL_BLOCK_TIMEOUT = 5000  # milliseconds
IDLE_POLL_INTERVAL_SECONDS = 1  # used when no methods are registered yet
HEARTBEAT_KEY_PREFIX = "anycall:heartbeat:"
HEARTBEAT_INTERVAL_SECONDS = 5
HEARTBEAT_TTL_SECONDS = HEARTBEAT_INTERVAL_SECONDS * 3


@dataclass
class MethodHandler:
    """Holder for registered method metadata."""
    bean: Any
    method: Callable
    parameter_type: type
    max_concurrency: int = 1


class AnyCallServer(ABC):
    """Interface for RPC server."""

    @abstractmethod
    def start(self) -> "AnyCallServer":
        """Start the server."""
        pass

    @abstractmethod
    def stop(self) -> None:
        """Stop the server."""
        pass

    @abstractmethod
    def is_running(self) -> bool:
        """Check if server is running."""
        pass

    @abstractmethod
    def register(self, *suppliers: Any) -> "AnyCallServer":
        """Register supplier(s) with this server."""
        pass

    @abstractmethod
    def unregister(self, method_name: str) -> "AnyCallServer":
        """Unregister a method."""
        pass


class AnyCallServerImpl(AnyCallServer):
    """RPC server implementation.

    One read loop listens on every registered method's stream via a single
    blocking XREADGROUP covering all of them at once, sharing one consumer
    group name (`queues.CONSUMER_GROUP_PREFIX`) across streams -- Redis scopes
    a group by (stream, name), so reusing the same literal name doesn't couple
    the methods together, and it's what lets one XREADGROUP call cover
    multiple streams (Redis only accepts one group name per call). This
    mirrors the Java implementation and keeps the two interoperable: a Java
    and a Python server can share the same consumer group on the same stream.

    Reads happen one message at a time per stream and dispatch to a shared
    worker pool without blocking the read loop (see `_dispatch_message`), so a
    saturated method only piles up its own worker tasks waiting on its
    semaphore, never stalls the loop. Bound that pileup with client-side
    `max_queue_depth` if it's a concern for a given method.

    Unlike the Java implementation -- which hand-splits a fixed read
    connection from a fixed write connection because its client library
    (Lettuce) can't issue a second command on a connection that's still
    blocked in a first -- this uses a single shared `redis.Redis` client for
    everything. redis-py's client is backed by a connection pool that already
    hands out a separate physical connection per concurrent call (blocking or
    not), so the single blocking read and any number of concurrent
    acks/deletes/writes never contend for the same socket.
    """

    def __init__(
        self,
        redis_adapter: RedisStreamAdapter,
        props: AnycallProperties,
        max_concurrency: Optional[int] = None,
    ):
        """
        Args:
            redis_adapter: Redis stream adapter
            props: Server configuration properties
            max_concurrency: Server-wide cap on requests processed at the same
                time, across every registered @supply method combined (see
                the `max_concurrency` argument of `supply`). None means
                uncapped -- the sum of each method's own max_concurrency
                applies instead.
        """
        if max_concurrency is not None and max_concurrency < 1:
            raise ValueError("AnyCall Server: max_concurrency must be at least 1")

        self.redis = redis_adapter
        self.props = props
        self.method_handlers: Dict[str, MethodHandler] = {}
        self._method_limiters: Dict[str, threading.Semaphore] = {}
        self._running = False
        self._running_lock = threading.Lock()
        self._executor: Optional[ThreadPoolExecutor] = None
        self._global_limiter = threading.Semaphore(max_concurrency) if max_concurrency else None
        self._server_id = f"server-{uuid.uuid4()}"
        self._heartbeat_key = f"{HEARTBEAT_KEY_PREFIX}{queues.CONSUMER_GROUP_PREFIX}:{self._server_id}"

    def register(self, *suppliers: Any) -> "AnyCallServer":
        """Register supplier(s) with this server."""
        for supplier in suppliers:
            self._register_supplier(supplier)
        return self

    def _register_supplier(self, supplier: Any) -> None:
        """Scan supplier for @supply methods and register them."""
        for name, method in inspect.getmembers(supplier, predicate=inspect.ismethod):
            if not hasattr(method, "_supply_method_name"):
                continue

            method_name = method._supply_method_name
            sig = inspect.signature(method)
            params = list(sig.parameters.values())

            if len(params) != 2:
                raise ValueError(
                    f"Method {name} must have exactly 2 parameters (AnycallContext, <request type>), "
                    f"got {len(params)}"
                )

            if params[0].annotation is not AnycallContext:
                raise ValueError(
                    f"Method {name} must declare AnycallContext as its first parameter"
                )

            param = params[1]
            parameter_type = param.annotation
            if parameter_type == inspect.Parameter.empty:
                raise ValueError(f"Method {name} parameter must have a type annotation")

            max_concurrency = getattr(method, "_supply_max_concurrency", 1)

            handler = MethodHandler(
                bean=supplier,
                method=method,
                parameter_type=parameter_type,
                max_concurrency=max_concurrency,
            )
            # Group creation happens here, synchronously, rather than lazily
            # on the read loop's next iteration: if it were deferred, a
            # register() called after start() could lose its first message --
            # a client publishing right after register() returns could beat
            # the loop to it, and XGROUP CREATE's implicit id="$" starts the
            # group at the stream's current tail, permanently skipping
            # whatever was already published before the group existed.
            # Creating it here means the group always exists before register()
            # returns, before any caller could possibly have published to it.
            self.redis.create_group(queues.request_queue(method_name), queues.CONSUMER_GROUP_PREFIX)
            self.method_handlers[method_name] = handler
            self._method_limiters[method_name] = threading.Semaphore(max_concurrency)
            # No per-method thread to start anymore -- the single read loop
            # already covers this stream on its next iteration.

    def start(self) -> "AnyCallServer":
        """Start the server."""
        with self._running_lock:
            if self._running:
                return self

            self._running = True
            worker_count = sum(h.max_concurrency for h in self.method_handlers.values())
            # +1 for the heartbeat loop, +1 for the single stream-reading loop.
            self._executor = ThreadPoolExecutor(max_workers=worker_count + 2)

            self._executor.submit(self._emit_heartbeats)
            self._executor.submit(self._poll_all_streams)

        return self

    def _emit_heartbeats(self) -> None:
        """Periodically writes a TTL'd heartbeat key so external tooling can
        detect a live server instance. Cleaned up on stop()."""
        while self._running:
            try:
                self.redis.set_with_ttl(self._heartbeat_key, str(int(time.time())), HEARTBEAT_TTL_SECONDS)
            except Exception as e:
                logger.warning(f"Failed to write heartbeat: {e}")
            time.sleep(HEARTBEAT_INTERVAL_SECONDS)

        try:
            self.redis.delete(self._heartbeat_key)
        except Exception as e:
            logger.debug(f"Failed to clean up heartbeat key {self._heartbeat_key}: {e}")

    def _poll_all_streams(self) -> None:
        """Single read loop for every registered method's stream. Every
        stream's group already exists by the time it can appear here -- see
        the comment in _register_supplier -- so this only ever reads."""
        logger.info("Started polling all registered method streams")

        while self._running:
            try:
                # Snapshot so a registration/unregistration mid-read doesn't
                # mutate the dict this iteration is working from.
                snapshot = dict(self.method_handlers)
                if not snapshot:
                    time.sleep(IDLE_POLL_INTERVAL_SECONDS)
                    continue

                streams = {queues.request_queue(name): ">" for name in snapshot}
                result = self.redis.read_group_multi(
                    streams, queues.CONSUMER_GROUP_PREFIX, self._server_id, POLL_BLOCK_TIMEOUT
                )

                if not result:
                    continue

                for stream_key, messages in result:
                    if isinstance(stream_key, bytes):
                        stream_key = stream_key.decode("utf-8")
                    for message_id, data in messages:
                        self._dispatch_message(stream_key, message_id, data, snapshot)

            except TimeoutError:
                pass
            except Exception as e:
                if self._running:
                    logger.exception(f"Error reading from streams: {e}")

    def _dispatch_message(
        self,
        stream_key: str,
        message_id: Any,
        data: Dict[bytes, bytes],
        snapshot: Dict[str, MethodHandler],
    ) -> None:
        """Routes one message to its handler and dispatches to the shared
        worker pool. Dispatch itself never blocks -- the method's
        max_concurrency and the server-wide cap, if any, are acquired inside
        the submitted task instead. A message with no handler (unregistered
        between being read and being routed) or missing its payload is
        dropped here directly, without going through the worker pool."""
        method_name = queues.method_name_from_stream(stream_key)
        handler = snapshot.get(method_name)

        if handler is None:
            logger.debug(f"Discarding message {message_id} for unregistered method (stream {stream_key})")
            self._ack_and_delete(stream_key, message_id)
            return

        if b"data" not in data:
            logger.warning(
                f"Discarding malformed message {message_id} on stream {stream_key}: missing 'data' field"
            )
            self._ack_and_delete(stream_key, message_id)
            return

        method_limiter = self._method_limiters.get(method_name)
        self._executor.submit(self._process_message, stream_key, message_id, data, handler, method_limiter)

    def _process_message(
        self,
        stream_key: str,
        message_id: Any,
        data: Dict[bytes, bytes],
        handler: MethodHandler,
        method_limiter: Optional[threading.Semaphore],
    ) -> None:
        method_acquired = False
        global_acquired = False
        try:
            if method_limiter is not None:
                method_limiter.acquire()
                method_acquired = True
            if self._global_limiter is not None:
                self._global_limiter.acquire()
                global_acquired = True

            self._process_request(handler, data)
            self._ack_and_delete(stream_key, message_id)
        except Exception as e:
            logger.exception(f"Error processing request: {e}")
        finally:
            if global_acquired:
                self._global_limiter.release()
            if method_acquired:
                method_limiter.release()

    def _ack_and_delete(self, stream_key: str, message_id: Any) -> None:
        self.redis.acknowledge(stream_key, queues.CONSUMER_GROUP_PREFIX, message_id)
        self.redis.delete_entry(stream_key, message_id)

    def _process_request(self, handler: MethodHandler, data: Dict[bytes, bytes]) -> None:
        """Process a single request and send response."""
        try:
            request_json = data[b"data"].decode("utf-8")
            rpc_request = deserialize(request_json, AnyCallRequest)

            param = deserialize(rpc_request.payload, handler.parameter_type)

            ctx = AnycallContext(request_id=rpc_request.request_id, method_name=rpc_request.method_name)
            result = handler.method(ctx, param)

            result_json = serialize(result)
            response = AnyCallResponse.success(rpc_request.request_id, result_json)

        except Exception as e:
            logger.exception(f"Error invoking method: {e}")
            response = AnyCallResponse.error(
                rpc_request.request_id if "rpc_request" in locals() else "unknown",
                str(e)
            )

        response_stream = queues.response_queue(response.request_id)
        response_json = serialize(response)
        self.redis.add(response_stream, {"data": response_json})

    def stop(self) -> None:
        """Stop the server."""
        with self._running_lock:
            if not self._running:
                return

            self._running = False

        if self._executor:
            self._executor.shutdown(wait=True)

    def is_running(self) -> bool:
        """Check if server is running."""
        return self._running

    def unregister(self, method_name: str) -> "AnyCallServer":
        """Unregister a method. Takes effect on the read loop's next
        iteration -- there's no per-method thread or connection to tear down
        anymore, since the whole server shares one read loop."""
        if method_name in self.method_handlers:
            del self.method_handlers[method_name]
            self._method_limiters.pop(method_name, None)
        return self
