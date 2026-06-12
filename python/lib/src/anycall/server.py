import inspect
import logging
import threading
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional

from . import queues
from .config import AnycallProperties
from .exceptions import AnyCallException
from .model import AnyCallRequest, AnyCallResponse
from .redis_adapter import RedisStreamAdapter
from .serialization import deserialize, serialize
from redis.exceptions import TimeoutError
logger = logging.getLogger(__name__)

POLL_BLOCK_TIMEOUT = 5000  # milliseconds


@dataclass
class MethodHandler:
    """Holder for registered method metadata."""
    bean: Any
    method: Callable
    parameter_type: type


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

    def __init__(self, redis_adapter: RedisStreamAdapter, props: AnycallProperties):
        self.redis = redis_adapter
        self.props = props
        self.method_handlers: Dict[str, MethodHandler] = {}
        self._running = False
        self._running_lock = threading.Lock()
        self._executor: Optional[ThreadPoolExecutor] = None

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

            if len(params) != 1:
                raise ValueError(
                    f"Method {name} must have exactly 1 parameter, got {len(params)}"
                )

            param = params[0]
            parameter_type = param.annotation
            if parameter_type == inspect.Parameter.empty:
                raise ValueError(f"Method {name} parameter must have a type annotation")

            handler = MethodHandler(bean=supplier, method=method, parameter_type=parameter_type)
            self.method_handlers[method_name] = handler

            if self._running:
                self._start_listener(method_name, handler)

    def start(self) -> "AnyCallServer":
        """Start the server."""
        with self._running_lock:
            if self._running:
                return self

            self._running = True
            self._executor = ThreadPoolExecutor(max_workers=len(self.method_handlers))

            for method_name, handler in self.method_handlers.items():
                self._start_listener(method_name, handler)

        return self

    def _start_listener(self, method_name: str, handler: MethodHandler) -> None:
        """Start a listener thread for a method."""
        stream_key = queues.request_queue(method_name)
        group_name = queues.consumer_group(method_name)
        consumer_id = f"consumer-{threading.current_thread().ident}"

        self.redis.create_group(stream_key, group_name)
        self._executor.submit(self._poll_stream, method_name, stream_key, group_name, consumer_id, handler)

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
                        try:
                            self._process_request(handler, data)
                            self.redis.acknowledge(stream_key, group_name, message_id)
                        except Exception as e:
                            logger.exception(f"Error processing request: {e}")

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

            result = handler.method(param)

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
