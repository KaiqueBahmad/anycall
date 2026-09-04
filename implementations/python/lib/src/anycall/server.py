import inspect
import logging
import random
import threading
import time
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

from redis.exceptions import TimeoutError

from . import queues
from .config import AnycallProperties
from .context import AnycallContext
from .model import AnyCallRequest, AnyCallResponse
from .redis_adapter import RedisQueueAdapter
from .serialization import deserialize, serialize

logger = logging.getLogger(__name__)

POLL_BLOCK_TIMEOUT_SECONDS = 5
IDLE_POLL_INTERVAL_SECONDS = 1  # used when no methods are registered yet


class ConcurrencyLimiter:
    """A counting semaphore that also exposes whether it has spare capacity
    right now, via `available()`. `threading.Semaphore` doesn't expose its
    count, but the read loop needs to peek before popping a request it might
    have nowhere to run yet."""

    def __init__(self, capacity: int):
        self._capacity = capacity
        self._in_use = 0
        self._condition = threading.Condition()

    def available(self) -> bool:
        with self._condition:
            return self._in_use < self._capacity

    def acquire(self) -> None:
        with self._condition:
            while self._in_use >= self._capacity:
                self._condition.wait()
            self._in_use += 1

    def release(self) -> None:
        with self._condition:
            self._in_use -= 1
            self._condition.notify()


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

    One read loop listens on every registered method's request queue via a
    single blocking BRPOP covering all of them at once. Only queues for
    methods with spare max_concurrency capacity right now are included (see
    `_methods_with_capacity`) -- a saturated method is excluded from the next
    BRPOP until one of its in-flight requests finishes, so requests for a
    busy method stay visible in Redis (accurate backlog for
    `get_queue_depth`/`max_queue_depth`) instead of being popped ahead of
    time and piling up in memory.

    Capacity is acquired synchronously on this read-loop thread, right after
    a request is popped and before it's dispatched to the worker pool (see
    `_dispatch_message`) -- since `_methods_with_capacity` already filtered
    for availability, this is normally instant; it only actually blocks the
    loop if that pre-filter's read was stale, which is exactly when the loop
    should wait rather than pop another request the method has no room for.

    Unlike the Java implementation -- which hand-splits a fixed read
    connection from a fixed write connection because its client library
    (Lettuce) can't issue a second command on a connection that's still
    blocked in a first -- this uses a single shared `redis.Redis` client for
    everything. redis-py's client is backed by a connection pool that already
    hands out a separate physical connection per concurrent call (blocking or
    not), so the single blocking read and any number of concurrent
    deletes/writes never contend for the same socket.
    """

    def __init__(
        self,
        redis_adapter: RedisQueueAdapter,
        props: AnycallProperties,
        max_concurrency: Optional[int] = None,
    ):
        """
        Args:
            redis_adapter: Redis queue adapter
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
        self._method_limiters: Dict[str, ConcurrencyLimiter] = {}
        self._running = False
        self._running_lock = threading.Lock()
        self._executor: Optional[ThreadPoolExecutor] = None
        self._global_limiter = ConcurrencyLimiter(max_concurrency) if max_concurrency else None
        self._in_flight_request_ids: set[str] = set()
        self._in_flight_lock = threading.Lock()

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
            self._method_limiters[method_name] = ConcurrencyLimiter(max_concurrency)
            # No per-method thread or Redis setup to do here -- the single
            # read loop already covers this queue on its next iteration, and
            # a Redis List needs no setup, it comes into existence on its
            # first LPUSH.

    def start(self) -> "AnyCallServer":
        """Start the server."""
        with self._running_lock:
            if self._running:
                return self

            self._running = True
            worker_count = sum(h.max_concurrency for h in self.method_handlers.values())
            # +1 for the single queue-reading loop.
            self._executor = ThreadPoolExecutor(max_workers=worker_count + 1)

            self._executor.submit(self._poll_all_queues)

        return self

    def get_in_flight_request_ids(self) -> set[str]:
        """Request ids currently between deserialization and response in
        `_process_request`. A snapshot, not a live view -- safe to iterate
        without external synchronization."""
        with self._in_flight_lock:
            return set(self._in_flight_request_ids)

    def _methods_with_capacity(self, method_names) -> List[str]:
        """Methods with a free slot right now: the server-wide cap (if any)
        has room, and the method's own max_concurrency limiter has room. A
        point-in-time read, not a reservation -- it can be stale by the time
        a slot is actually acquired in `_dispatch_message`. That's fine:
        worst case one extra request gets popped just as its method fills
        up."""
        if self._global_limiter is not None and not self._global_limiter.available():
            return []
        available = []
        for name in method_names:
            limiter = self._method_limiters.get(name)
            if limiter is None or limiter.available():
                available.append(name)
        return available

    def _poll_all_queues(self) -> None:
        """Single read loop for every registered method's request queue."""
        logger.info("Started polling all registered method queues")

        while self._running:
            try:
                # Snapshot so a registration/unregistration mid-read doesn't
                # mutate the dict this iteration is working from.
                snapshot = dict(self.method_handlers)
                if not snapshot:
                    time.sleep(IDLE_POLL_INTERVAL_SECONDS)
                    continue

                available_methods = self._methods_with_capacity(snapshot.keys())
                if not available_methods:
                    # Every registered method (or the server-wide cap) is
                    # fully saturated right now -- back off instead of
                    # busy-looping.
                    time.sleep(IDLE_POLL_INTERVAL_SECONDS)
                    continue

                queue_keys = [queues.request_queue(name) for name in available_methods]
                # Shuffled so BRPOP's preference for the first key with data
                # available doesn't starve a method that consistently sorts
                # after a busier one.
                random.shuffle(queue_keys)

                result = self.redis.pop(queue_keys, POLL_BLOCK_TIMEOUT_SECONDS)
                if result is None:
                    continue

                queue_key, request_json = result
                self._dispatch_message(queue_key, request_json, snapshot)

            except TimeoutError:
                pass
            except Exception as e:
                if self._running:
                    logger.exception(f"Error reading from queues: {e}")

    def _dispatch_message(
        self,
        queue_key: str,
        request_json: str,
        snapshot: Dict[str, MethodHandler],
    ) -> None:
        """Routes one popped request to its handler. Acquires capacity on
        this thread, before dispatching to the worker pool -- see the class
        docstring for why that's safe and necessary. A request with no
        handler (unregistered between being popped and being routed) is
        dropped directly; BRPOP already removed it from Redis, so there's
        nothing left to clean up."""
        method_name = queues.method_name_from_queue(queue_key)
        handler = snapshot.get(method_name)

        if handler is None:
            logger.debug(f"Discarding request for unregistered method (queue {queue_key})")
            return

        method_limiter = self._method_limiters.get(method_name)
        if method_limiter is not None:
            method_limiter.acquire()
        if self._global_limiter is not None:
            self._global_limiter.acquire()

        self._executor.submit(self._process_message, request_json, handler, method_limiter)

    def _process_message(
        self,
        request_json: str,
        handler: MethodHandler,
        method_limiter: Optional[ConcurrencyLimiter],
    ) -> None:
        try:
            self._process_request(handler, request_json)
        except Exception as e:
            logger.exception(f"Error processing request: {e}")
        finally:
            if self._global_limiter is not None:
                self._global_limiter.release()
            if method_limiter is not None:
                method_limiter.release()

    def _process_request(self, handler: MethodHandler, request_json: str) -> None:
        """Process a single request and send response."""
        request_id = None
        try:
            rpc_request = deserialize(request_json, AnyCallRequest)
            request_id = rpc_request.request_id
            with self._in_flight_lock:
                self._in_flight_request_ids.add(request_id)

            param = deserialize(rpc_request.payload, handler.parameter_type)

            ctx = AnycallContext(request_id=rpc_request.request_id, method_name=rpc_request.method_name)
            result = handler.method(ctx, param)

            result_json = serialize(result)
            response = AnyCallResponse.success(rpc_request.request_id, result_json)

        except Exception as e:
            logger.exception(f"Error invoking method: {e}")
            response = AnyCallResponse.error(
                request_id if request_id is not None else "unknown",
                str(e)
            )
        finally:
            if request_id is not None:
                with self._in_flight_lock:
                    self._in_flight_request_ids.discard(request_id)

        response_queue = queues.response_queue(response.request_id)
        response_json = serialize(response)
        self.redis.push(response_queue, response_json)

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
