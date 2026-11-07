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
from .model import AnyCallRequest, AnyCallResponse
from .reaping import reap_dead_servers
from .redis_adapter import RedisQueueAdapter
from .serialization import deserialize, serialize

logger = logging.getLogger(__name__)

# How long a method's read loop blocks on its queue before looking again, in
# whole seconds (BRPOPLPUSH's unit). Bounds how long `stop` and `unregister`
# take to reach an idle loop; an idle loop costs one command per this period.
TAKE_BLOCK_SECONDS = 2

# Liveness registry. Hardcoded on purpose -- edit here to change it; there is no
# configuration surface for these. HEARTBEAT_KEY/HEARTBEAT_TTL_SECONDS live in
# `queues` so the client can share them for its own liveness check.
HEARTBEAT_KEY = queues.HEARTBEAT_KEY
HEARTBEAT_PERIOD_SECONDS = 2  # how often a live server refreshes its entry
HEARTBEAT_TTL_SECONDS = queues.HEARTBEAT_TTL_SECONDS


class ConcurrencyLimiter:
    """A counting semaphore whose `acquire` can give up after a timeout, so a
    read loop waiting for a free slot still notices the server stopping."""

    def __init__(self, capacity: int):
        self._capacity = capacity
        self._in_use = 0
        self._condition = threading.Condition()

    def acquire(self, timeout: Optional[float] = None) -> bool:
        with self._condition:
            if not self._condition.wait_for(lambda: self._in_use < self._capacity, timeout):
                return False
            self._in_use += 1
            return True

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

    Every registered method gets a read loop of its own, which takes its
    requests with one BRPOPLPUSH (see `RedisQueueAdapter.take`): the request
    moves from the method's queue onto this server's processing list
    (`anycall:processing:<server id>`) in one atomic step, so a crash at any
    point leaves it either still queued or on the list of the server that had
    it -- never neither. BRPOPLPUSH blocks, so an idle loop waits in Redis and
    is handed a request the moment a client pushes one, and of several idle
    servers, Redis hands it to exactly one.

    A loop only asks for its next request when its method has a free
    max_concurrency slot, so requests for a busy method stay in their queue
    (an accurate backlog for `get_queue_depth`/`max_queue_depth`). The
    server-wide `max_concurrency`, if set, gates running a request rather
    than taking it: a loop blocked in Redis can't hold a server-wide slot
    without starving the other methods, so a request taken while every slot
    is busy waits here for one, already safe on the processing list. That
    overshoots the cap on taking by at most one request per method.

    Every heartbeat tick also fails back the requests of servers that stopped
    heartbeating (see `reaping.reap_dead_servers`): their clients get a
    ServerLostError instead of waiting out their whole timeout.

    BRPOPLPUSH reads a single queue and holds its connection while it blocks,
    so the server uses one Redis connection per method, plus the ones redis-
    py's pool hands out for responses and the heartbeat.
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
        self._threads: list[threading.Thread] = []
        self._global_limiter = ConcurrencyLimiter(max_concurrency) if max_concurrency else None
        self._server_id = str(uuid.uuid4())
        self._processing_key = queues.processing_list(self._server_id)
        self._in_flight_request_ids: set[str] = set()
        self._in_flight_lock = threading.Lock()
        self._heartbeat_registered = False

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
            with self._running_lock:
                self._method_limiters[method_name] = ConcurrencyLimiter(max_concurrency)
                # Replacing a handler makes the old one's loop exit on its next
                # iteration; the new one gets a loop of its own.
                self.method_handlers[method_name] = handler
                if self._running:
                    self._start_reader(method_name, handler)

    def start(self) -> "AnyCallServer":
        """Start the server."""
        with self._running_lock:
            if self._running:
                return self

            self._running = True
            worker_count = sum(h.max_concurrency for h in self.method_handlers.values())
            self._executor = ThreadPoolExecutor(max_workers=max(worker_count, 1))

            logger.info(f"Starting AnyCall server {self._server_id}")
            # Heartbeat once before taking any request: a server missing from
            # the live set is never looked at by reaping, so this server must be
            # in it before its processing list holds anything.
            self._heartbeat_tick()
            self._start_thread(self._emit_heartbeats, "anycall-heartbeat")
            for method_name, handler in self.method_handlers.items():
                self._start_reader(method_name, handler)

        return self

    def _start_thread(self, target: Callable, name: str, *args: Any) -> None:
        thread = threading.Thread(target=target, args=args, name=name, daemon=True)
        self._threads.append(thread)
        thread.start()

    def _start_reader(self, method_name: str, handler: MethodHandler) -> None:
        self._start_thread(self._read_method, f"anycall-read-{method_name}", method_name, handler)

    @property
    def server_id(self) -> str:
        """This server instance's id -- the member it registers under in
        `HEARTBEAT_KEY`. Generated at construction, stable for the instance's
        lifetime, and not reused across restarts."""
        return self._server_id

    def get_in_flight_request_ids(self) -> set[str]:
        """Request ids currently between deserialization and response in
        `_process_request`. A snapshot, not a live view -- safe to iterate
        without external synchronization."""
        with self._in_flight_lock:
            return set(self._in_flight_request_ids)

    def _emit_heartbeats(self) -> None:
        """Keeps this server's entry in the `HEARTBEAT_KEY` sorted set fresh, so
        clients and external tooling can tell it's alive by reading back the
        members scored within HEARTBEAT_TTL_SECONDS of Redis's current time
        (`TIME`).

        Runs on its own thread so a slow or unreachable Redis never delays the
        read loops. `start` already ran the first tick, so this one sleeps
        first.
        """
        while self._running:
            time.sleep(HEARTBEAT_PERIOD_SECONDS)
            if self._running:
                self._heartbeat_tick()

    def _heartbeat_tick(self) -> None:
        """One heartbeat (see `RedisQueueAdapter.heartbeat`), then fail back
        whatever the servers it found dead were still processing."""
        try:
            rejoined, dead = self.redis.heartbeat(HEARTBEAT_KEY, self._server_id, HEARTBEAT_TTL_SECONDS)
        except Exception as e:
            logger.warning(f"Failed to write heartbeat: {e}")
            return

        if rejoined and self._heartbeat_registered:
            logger.warning(
                f"Server {self._server_id} was reaped as dead (no heartbeat for over "
                f"{HEARTBEAT_TTL_SECONDS}s); the requests it was processing have been "
                f"failed back to their clients"
            )
        self._heartbeat_registered = True

        reap_dead_servers(self.redis, dead)

    def _read_method(self, method_name: str, handler: MethodHandler) -> None:
        """Read loop for one method's queue, until the server stops or the
        method is unregistered (or registered again, which starts a new loop).
        Waits for a free slot of the method before every take, so it never
        takes a request it has no room to run."""
        queue_key = queues.request_queue(method_name)
        limiter = self._method_limiters[method_name]
        logger.info(f"Started reading queue {queue_key}")

        while self._running and self.method_handlers.get(method_name) is handler:
            if not limiter.acquire(timeout=TAKE_BLOCK_SECONDS):
                continue
            try:
                item = self.redis.take(queue_key, self._processing_key, TAKE_BLOCK_SECONDS)
            except Exception as e:
                limiter.release()
                if self._running:
                    logger.warning(f"Error reading from queue {queue_key}: {e}")
                    time.sleep(1)
                continue
            if item is None:
                limiter.release()
                continue

            # Waits for a server-wide slot here, not before taking: see the
            # class docstring. The request is already on the processing list.
            if self._global_limiter is not None:
                self._global_limiter.acquire()
            try:
                self._executor.submit(self._process_message, item, handler, limiter)
            except RuntimeError:
                # The worker pool shut down under us (`stop` joins the loops first,
                # so this shouldn't happen). The request stays on the processing
                # list and is failed back once this server stops heartbeating.
                self._release_slots(limiter)
                return

    def _release_slots(self, method_limiter: ConcurrencyLimiter) -> None:
        if self._global_limiter is not None:
            self._global_limiter.release()
        method_limiter.release()

    def _process_message(self, item: str, handler: MethodHandler, method_limiter: ConcurrencyLimiter) -> None:
        try:
            self._process_request(handler, item)
        except Exception as e:
            logger.exception(f"Error processing request: {e}")
        finally:
            self._release_slots(method_limiter)

    def _process_request(self, handler: MethodHandler, item: str) -> None:
        """Process a single request and send response.

        `item` is the request json exactly as it was taken onto the processing
        list; it's removed from there along with sending the response, even if
        the request fails to deserialize here.
        """
        request_id = None
        try:
            rpc_request = deserialize(item, AnyCallRequest)
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
        self.redis.respond(
            response_queue, response_json, queues.RESPONSE_TTL_SECONDS, self._processing_key, item
        )

    def stop(self) -> None:
        """Stop the server. Read loops notice within TAKE_BLOCK_SECONDS; the
        requests already taken are run to completion and answered."""
        with self._running_lock:
            if not self._running:
                return

            self._running = False
            threads, self._threads = self._threads, []

        for thread in threads:
            thread.join()
        if self._executor:
            self._executor.shutdown(wait=True)

    def is_running(self) -> bool:
        """Check if server is running."""
        return self._running

    def unregister(self, method_name: str) -> "AnyCallServer":
        """Unregister a method. Its read loop exits within TAKE_BLOCK_SECONDS;
        a request it takes in the meantime is still run and answered."""
        with self._running_lock:
            if method_name in self.method_handlers:
                del self.method_handlers[method_name]
        return self
