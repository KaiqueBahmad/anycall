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
    """RPC server implementation."""

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
            self.method_handlers[method_name] = handler

            if self._running:
                self._start_listeners(method_name, handler)

    def start(self) -> "AnyCallServer":
        """Start the server."""
        with self._running_lock:
            if self._running:
                return self

            self._running = True
            worker_count = sum(h.max_concurrency for h in self.method_handlers.values())
            self._executor = ThreadPoolExecutor(max_workers=worker_count + 1)

            self._executor.submit(self._emit_heartbeats)
            for method_name, handler in self.method_handlers.items():
                self._start_listeners(method_name, handler)

        return self

    def _start_listeners(self, method_name: str, handler: MethodHandler) -> None:
        """Start `handler.max_concurrency` listener threads for a method.

        Every worker shares the same consumer group -- Redis's consumer group
        distributes pending messages across consumers, so raising
        max_concurrency simply lets more workers pull from the same stream at
        once.
        """
        stream_key = queues.request_queue(method_name)
        group_name = queues.consumer_group(method_name)

        self.redis.create_group(stream_key, group_name)
        for _ in range(handler.max_concurrency):
            consumer_id = f"consumer-{uuid.uuid4()}"
            self._executor.submit(self._poll_stream, method_name, stream_key, group_name, consumer_id, handler)

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

    def _poll_stream(
        self,
        method_name: str,
        stream_key: str,
        group_name: str,
        consumer_id: str,
        handler: MethodHandler
    ) -> None:
        """Poll stream for requests and process them."""
        logger.info(f"Started polling stream for method: {method_name}")

        while self._running:
            try:
                result = self.redis.read_group(stream_key, group_name, consumer_id, POLL_BLOCK_TIMEOUT)

                if result is None:
                    continue

                for stream, messages in result:
                    for message_id, data in messages:
                        global_acquired = False
                        try:
                            if self._global_limiter is not None:
                                self._global_limiter.acquire()
                                global_acquired = True

                            if b"data" not in data:
                                logger.warning(
                                    f"Discarding malformed message {message_id} on stream {stream_key}: "
                                    f"missing 'data' field"
                                )
                            else:
                                self._process_request(handler, data)

                            self.redis.acknowledge(stream_key, group_name, message_id)
                            self.redis.delete_entry(stream_key, message_id)
                        except Exception as e:
                            logger.exception(f"Error processing request: {e}")
                        finally:
                            if global_acquired:
                                self._global_limiter.release()

            except TimeoutError:
                pass
            except Exception as e:
                logger.exception(f"Error reading from stream: {e}")

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
        """Unregister a method."""
        if method_name in self.method_handlers:
            del self.method_handlers[method_name]
        return self
