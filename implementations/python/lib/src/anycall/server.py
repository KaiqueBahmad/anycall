import inspect
import logging
import random
import threading
import time
import uuid
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

from redis.exceptions import TimeoutError

from . import queues
from .config import AnycallProperties
from .context import AnycallContext
from .model import AnyCallRequest, AnyCallResponse
from .reaping import reap_orphans
from .redis_adapter import RedisQueueAdapter
from .serialization import deserialize, serialize

logger = logging.getLogger(__name__)

# How long the read loop waits for a wake (or a freed slot) before looking at
# its queues anyway -- the safety net for a wake missed during a reconnect, or
# published by a client that predates wakes.
WAKE_FALLBACK_SECONDS = 1
# How often the wake listener picks up registrations/unregistrations made
# since it last (un)subscribed.
WAKE_LISTEN_TICK_SECONDS = 0.5

# Liveness registry. Hardcoded on purpose -- edit here to change it; there is no
# configuration surface for these. HEARTBEAT_KEY/HEARTBEAT_TTL_SECONDS live in
# `queues` so the client can share them for its own liveness check.
HEARTBEAT_KEY = queues.HEARTBEAT_KEY
HEARTBEAT_PERIOD_SECONDS = 2  # how often a live server refreshes its entry
HEARTBEAT_TTL_SECONDS = queues.HEARTBEAT_TTL_SECONDS
INFLIGHT_KEY = queues.INFLIGHT_KEY


class Doorbell:
    """Tells the read loop to look at its queues again: a wake arrived for
    one of its methods, a local slot freed up, or the method set changed.
    Rings are coalesced -- the loop only needs to know "look again", not how
    many times. A ring that lands while the loop is busy is kept, so the
    loop's next `wait` returns straight away instead of missing it."""

    def __init__(self) -> None:
        self._rung = False
        self._condition = threading.Condition()

    def ring(self) -> None:
        with self._condition:
            self._rung = True
            self._condition.notify_all()

    def clear(self) -> None:
        with self._condition:
            self._rung = False

    def wait(self, timeout: float) -> None:
        with self._condition:
            if not self._rung:
                self._condition.wait(timeout)
            self._rung = False


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

    One read loop takes requests off every registered method's queue. Each
    take runs ACQUIRE_SCRIPT (see `RedisQueueAdapter.acquire`), which pops
    the request and records this server as its owner in `INFLIGHT_KEY` in
    one atomic step, so a crash at any point leaves either the request still
    queued or a record of who had it -- never neither. Only queues for
    methods with spare max_concurrency capacity right now are tried (see
    `_methods_with_capacity`), so requests for a busy method stay visible in
    Redis (accurate backlog for `get_queue_depth`/`max_queue_depth`) instead
    of being popped ahead of time and piling up in memory.

    A script can't block, so the loop doesn't either: when there's nothing
    to take it waits on a `Doorbell`, rung by a wake message for one of its
    methods (clients publish on `anycall:wake:<method>` after every push,
    see `_listen_for_wakes`), by a worker freeing a slot, or after
    WAKE_FALLBACK_SECONDS regardless. It always tries its queues before
    waiting, so requests already queued at startup or after a busy spell are
    picked up without needing a wake.

    Every heartbeat tick also fails back the in-flight requests of servers
    that stopped heartbeating (see `reaping.reap_orphans`): their clients get a
    ServerLostError instead of waiting out their whole timeout.

    Capacity is acquired synchronously on this read-loop thread, right after
    a request is taken and before it's dispatched to the worker pool (see
    `_dispatch_message`) -- since `_methods_with_capacity` already filtered
    for availability, this is normally instant; it only actually blocks the
    loop if that pre-filter's read was stale, which is exactly when the loop
    should wait rather than take another request the method has no room for.

    Unlike the Java implementation -- which hand-splits a fixed read
    connection from a fixed write connection because its client library
    (Lettuce) can't issue a second command on a connection that's still
    blocked in a first -- this uses a single shared `redis.Redis` client for
    everything. redis-py's client is backed by a connection pool that already
    hands out a separate physical connection per concurrent call (blocking or
    not), so the single blocking read and any number of concurrent
    deletes/writes never contend for the same socket. The wake listener is
    the exception: a Pub/Sub subscription holds its connection for good, so
    it gets its own.
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
        self._server_id = str(uuid.uuid4())
        self._in_flight_request_ids: set[str] = set()
        self._in_flight_lock = threading.Lock()
        self._doorbell = Doorbell()
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
            self.method_handlers[method_name] = handler
            self._method_limiters[method_name] = ConcurrencyLimiter(max_concurrency)
            # No per-method thread or Redis setup to do here -- the read loop
            # covers this queue on its next iteration (rung right away) and the
            # wake listener subscribes to its channel on its next tick; a Redis
            # List needs no setup, it comes into existence on its first LPUSH.
            self._doorbell.ring()

    def start(self) -> "AnyCallServer":
        """Start the server."""
        with self._running_lock:
            if self._running:
                return self

            self._running = True
            worker_count = sum(h.max_concurrency for h in self.method_handlers.values())
            # +1 each for the queue-reading loop, the heartbeat loop and the
            # wake listener.
            self._executor = ThreadPoolExecutor(max_workers=worker_count + 3)

            logger.info(f"Starting AnyCall server {self._server_id}")
            # Heartbeat once before taking any request: another server's
            # cleanup treats an in-flight owner missing from the live set as
            # dead, so this server must be in it before it owns anything.
            self._heartbeat_tick()
            self._executor.submit(self._poll_all_queues)
            self._executor.submit(self._emit_heartbeats)
            self._executor.submit(self._listen_for_wakes)

        return self

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
        external tooling can list live servers by reading back the members scored
        within HEARTBEAT_TTL_SECONDS of Redis's current time (`TIME`).

        Runs on its own thread so a slow or unreachable Redis never delays
        `_poll_all_queues` from draining its queues. `start` already ran the
        first tick, so this one sleeps first.
        """
        while self._running:
            time.sleep(HEARTBEAT_PERIOD_SECONDS)
            self._heartbeat_tick()

    def _heartbeat_tick(self) -> None:
        """One heartbeat (see `RedisQueueAdapter.heartbeat`, which also prunes
        the entries that stopped being refreshed), then fail back whatever the
        servers found dead were still processing."""
        try:
            # Read before the live set, never after: an owner must heartbeat
            # before it can take a request, so any owner in this snapshot was
            # in the live set first, and is missing from the one read below
            # only if it really stopped heartbeating.
            owners = self.redis.inflight_owners(INFLIGHT_KEY)
            rejoined, alive = self.redis.heartbeat(HEARTBEAT_KEY, self._server_id, HEARTBEAT_TTL_SECONDS)
        except Exception as e:
            logger.warning(f"Failed to write heartbeat: {e}")
            return

        if rejoined and self._heartbeat_registered:
            logger.warning(
                f"Server {self._server_id} was pruned as dead (no heartbeat for over "
                f"{HEARTBEAT_TTL_SECONDS}s); the requests it was processing may already "
                f"have been failed back to their clients"
            )
        self._heartbeat_registered = True

        reap_orphans(self.redis, owners, alive)

    def _listen_for_wakes(self) -> None:
        """Keeps a Pub/Sub subscription to the wake channel of every
        registered method and rings the doorbell on each message.

        A wake is only a hint, so losing one is harmless -- the read loop
        looks at its queues every WAKE_FALLBACK_SECONDS anyway. The doorbell
        is also rung after every (re)subscribe, since a request could have
        landed before the subscription existed.

        Owns its Pub/Sub handle outright (redis-py's isn't thread-safe), so
        (un)subscribing for methods registered/unregistered at runtime is
        done here too, each tick, rather than from the registering thread.
        """
        pubsub = None
        subscribed: set[str] = set()

        while self._running:
            try:
                if pubsub is None:
                    pubsub = self.redis.subscriber()
                    subscribed = set()

                wanted = {queues.wake_channel(name) for name in list(self.method_handlers)}
                added = wanted - subscribed
                removed = subscribed - wanted
                if added:
                    pubsub.subscribe(*added)
                if removed:
                    pubsub.unsubscribe(*removed)
                subscribed = wanted
                if added:
                    self._doorbell.ring()

                if not subscribed:
                    time.sleep(WAKE_LISTEN_TICK_SECONDS)
                    continue

                message = pubsub.get_message(timeout=WAKE_LISTEN_TICK_SECONDS)
                if message is not None:
                    self._doorbell.ring()
            except Exception as e:
                if self._running:
                    logger.warning(f"Wake listener failed, resubscribing: {e}")
                if pubsub is not None:
                    try:
                        pubsub.close()
                    except Exception:
                        pass
                pubsub = None
                time.sleep(WAKE_FALLBACK_SECONDS)

        if pubsub is not None:
            pubsub.close()

    def _methods_with_capacity(self, method_names) -> List[str]:
        """Methods with a free slot right now: the server-wide cap (if any)
        has room, and the method's own max_concurrency limiter has room. A
        point-in-time read, not a reservation -- it can be stale by the time
        a slot is actually acquired in `_dispatch_message`. That's fine:
        worst case one extra request gets taken just as its method fills
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
                available_methods = self._methods_with_capacity(snapshot.keys())
                if not available_methods:
                    # Nothing registered, or every registered method (or the
                    # server-wide cap) is saturated: a worker finishing rings
                    # the doorbell, so wait for that instead of busy-looping.
                    self._doorbell.wait(WAKE_FALLBACK_SECONDS)
                    continue

                queue_keys = [queues.request_queue(name) for name in available_methods]
                # Shuffled so the script's preference for the first queue with
                # data doesn't starve a method that consistently sorts after a
                # busier one.
                random.shuffle(queue_keys)

                # Cleared before looking, not after: a wake that lands while
                # the script runs stays rung, so the wait below returns at once.
                self._doorbell.clear()
                acquired = self.redis.acquire(INFLIGHT_KEY, queue_keys, self._server_id)
                if acquired is None:
                    self._doorbell.wait(WAKE_FALLBACK_SECONDS)
                    continue

                queue_key, request_json, request_id = acquired
                self._dispatch_message(queue_key, request_json, request_id, snapshot)

            except TimeoutError:
                pass
            except Exception as e:
                if self._running:
                    logger.exception(f"Error reading from queues: {e}")

    def _dispatch_message(
        self,
        queue_key: str,
        request_json: str,
        request_id: str,
        snapshot: Dict[str, MethodHandler],
    ) -> None:
        """Routes one taken request to its handler. Acquires capacity on
        this thread, before dispatching to the worker pool -- see the class
        docstring for why that's safe and necessary. A request with no
        handler (unregistered between being taken and being routed) is
        dropped, along with its in-flight entry."""
        method_name = queues.method_name_from_queue(queue_key)
        handler = snapshot.get(method_name)

        if handler is None:
            logger.debug(f"Discarding request for unregistered method (queue {queue_key})")
            if request_id:
                self.redis.release_inflight(INFLIGHT_KEY, request_id)
            return

        method_limiter = self._method_limiters.get(method_name)
        if method_limiter is not None:
            method_limiter.acquire()
        if self._global_limiter is not None:
            self._global_limiter.acquire()

        self._executor.submit(self._process_message, request_json, request_id, handler, method_limiter)

    def _process_message(
        self,
        request_json: str,
        acquired_id: str,
        handler: MethodHandler,
        method_limiter: Optional[ConcurrencyLimiter],
    ) -> None:
        try:
            self._process_request(handler, request_json, acquired_id)
        except Exception as e:
            logger.exception(f"Error processing request: {e}")
        finally:
            if self._global_limiter is not None:
                self._global_limiter.release()
            if method_limiter is not None:
                method_limiter.release()
            # A slot just freed up: have the read loop look for more work now
            # rather than on its next fallback tick.
            self._doorbell.ring()

    def _process_request(self, handler: MethodHandler, request_json: str, acquired_id: str) -> None:
        """Process a single request and send response.

        `acquired_id` is the request id ACQUIRE_SCRIPT recorded in the
        in-flight hash ('' if it couldn't parse one); the entry is dropped
        under that id along with sending the response, even if the request
        fails to deserialize here.
        """
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
        self.redis.respond(response_queue, response_json, queues.RESPONSE_TTL_SECONDS, INFLIGHT_KEY, acquired_id)

    def stop(self) -> None:
        """Stop the server."""
        with self._running_lock:
            if not self._running:
                return

            self._running = False

        self._doorbell.ring()
        if self._executor:
            self._executor.shutdown(wait=True)

    def is_running(self) -> bool:
        """Check if server is running."""
        return self._running

    def unregister(self, method_name: str) -> "AnyCallServer":
        """Unregister a method. Takes effect on the read loop's next
        iteration and the wake listener's next tick -- there's no per-method
        thread or connection to tear down, since the whole server shares one
        read loop."""
        if method_name in self.method_handlers:
            del self.method_handlers[method_name]
            self._method_limiters.pop(method_name, None)
            self._doorbell.ring()
        return self
