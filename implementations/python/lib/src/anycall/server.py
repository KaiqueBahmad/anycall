import inspect
import logging
import threading
import time
import uuid
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional

import redis.exceptions

from . import queues
from .context import AnycallContext
from .exceptions import AnyCallError
from .model import AnyCallRequest, AnyCallResponse, read_reply_address
from .reaping import reap_dead_servers
from .redis_adapter import RedisQueueAdapter
from .serialization import deserialize, serialize

logger = logging.getLogger(__name__)

# How long a method's read loop blocks on its queue before looking again, in
# whole seconds (a take's unit). Bounds how long `stop` and `unregister`
# take to reach an idle loop; an idle loop costs one command per this period.
TAKE_BLOCK_SECONDS = 2

# Liveness registry. Hardcoded on purpose -- edit here to change it; there is no
# configuration surface for these. HEARTBEAT_KEY/HEARTBEAT_TTL_SECONDS live in
# `queues` so the client can share them for its own liveness check.
HEARTBEAT_KEY = queues.HEARTBEAT_KEY
HEARTBEAT_PERIOD_SECONDS = 2  # how often a live server refreshes its entry
HEARTBEAT_TTL_SECONDS = queues.HEARTBEAT_TTL_SECONDS


class _Identity:
    """The server id a server heartbeats and takes requests under. Replaced by
    a new one when the server is declared dead, and the old one drains (see
    `AnyCallServerImpl._drain`): requests taken under it are failed back by
    reapers, so their results are discarded."""

    def __init__(self) -> None:
        self.server_id = str(uuid.uuid4())
        self.processing_key = queues.processing_list(self.server_id)
        # Whether its first heartbeat went through: no request is taken
        # under an id before that.
        self.registered = False
        # Takes started under this id and not returned yet, guarded by the
        # server's identity lock. Once it drains and this reaches 0, nothing
        # can land on its list anymore, and its tombstone can go.
        self.active_takes = 0


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
    requests with one BLMOVE, or BRPOPLPUSH on a Redis before 6.2 (see
    `RedisQueueAdapter.take`): the request
    moves from the method's queue onto this server's processing list
    (`anycall:processing:<server id>`) in one atomic step, so a crash at any
    point leaves it either still queued or on the list of the server that had
    it -- never neither. A take blocks, so an idle loop waits in Redis and
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

    A take reads a single queue and holds its connection while it blocks,
    so the server uses one Redis connection per method, plus the ones redis-
    py's pool hands out for responses and the heartbeat.
    """

    def __init__(
        self,
        redis_adapter: RedisQueueAdapter,
        max_concurrency: Optional[int] = None,
    ):
        """
        Args:
            redis_adapter: Redis queue adapter
            max_concurrency: Server-wide cap on requests processed at the same
                time, across every registered @supply method combined (see
                the `max_concurrency` argument of `supply`). None means
                uncapped -- the sum of each method's own max_concurrency
                applies instead.
        """
        if max_concurrency is not None and max_concurrency < 1:
            raise ValueError("AnyCall Server: max_concurrency must be at least 1")

        self.redis = redis_adapter
        self.method_handlers: Dict[str, MethodHandler] = {}
        self._method_limiters: Dict[str, ConcurrencyLimiter] = {}
        self._running = False
        self._running_lock = threading.Lock()
        self._executor: Optional[ThreadPoolExecutor] = None
        self._threads: list[threading.Thread] = []
        self._global_limiter = ConcurrencyLimiter(max_concurrency) if max_concurrency else None
        self._identity = _Identity()
        # Guards `_identity`, `_draining` and every identity's `active_takes`:
        # a read loop counts its take under the same lock a drain switches
        # ids under, so once an id drains, no new take can start on it.
        self._identity_lock = threading.Lock()
        # Ids that drained and whose tombstone still has to be deleted.
        self._draining: list[_Identity] = []
        # Set while the current id is registered, so read loops can take.
        self._registered = threading.Event()
        # Wakes the heartbeat early, to register a new id right after a drain.
        self._heartbeat_wake = threading.Event()
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
            with self._running_lock:
                self._method_limiters[method_name] = ConcurrencyLimiter(max_concurrency)
                # Replacing a handler makes the old one's loop exit on its next
                # iteration; the new one gets a loop of its own.
                self.method_handlers[method_name] = handler
                if self._running:
                    self._start_reader(method_name, handler)

    def start(self) -> "AnyCallServer":
        """Start the server.

        Raises:
            AnyCallError: If the first heartbeat fails; the server is left
                stopped and can be started again.
        """
        with self._running_lock:
            if self._running:
                return self

            # A restart starts clean: the last run's id ages out with an empty list.
            if self._identity.registered:
                self._identity = _Identity()
                self._registered.clear()
            logger.info(f"Starting AnyCall server {self._identity.server_id}")
            try:
                uses_blmove = self.redis.detect_blmove()
            except Exception as e:
                raise AnyCallError(
                    "AnyCall Server", f"Failed to ask Redis for BLMOVE, not starting: {e}"
                ) from e
            logger.info(f"Taking requests with {'BLMOVE' if uses_blmove else 'BRPOPLPUSH'}")
            # Heartbeat once before taking any request: a server missing from
            # the live set is never looked at by reaping, so a request it took
            # would be lost if it then crashed.
            try:
                self._heartbeat()
            except Exception as e:
                raise AnyCallError(
                    "AnyCall Server", f"Failed to write the first heartbeat, not starting: {e}"
                ) from e

            self._running = True
            worker_count = sum(h.max_concurrency for h in self.method_handlers.values())
            self._executor = ThreadPoolExecutor(max_workers=max(worker_count, 1))
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
        """This server's current id -- the member it registers under in
        `HEARTBEAT_KEY`. A new one is generated on every start, and whenever
        the server is declared dead; an id is never reused."""
        return self._identity.server_id

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
            self._heartbeat_wake.wait(HEARTBEAT_PERIOD_SECONDS)
            self._heartbeat_wake.clear()
            if self._running:
                self._heartbeat_tick()

    def _heartbeat_tick(self) -> None:
        """A heartbeat of the running server: a failure only logs, and the
        next tick tries again."""
        try:
            self._heartbeat()
        except Exception as e:
            logger.warning(f"Failed to write heartbeat: {e}")

    def _heartbeat(self) -> None:
        """One heartbeat (see `RedisQueueAdapter.heartbeat`), then fail back
        whatever the servers it found dead were still processing. If this
        server was declared dead meanwhile, its id drains and it heartbeats
        under a new one instead (see `_drain`). Raises if the heartbeat
        itself fails; reaping failures only log."""
        identity = self._identity
        dead = self.redis.heartbeat(
            HEARTBEAT_KEY, identity.server_id, HEARTBEAT_TTL_SECONDS, first=not identity.registered
        )
        if dead is None:
            self._drain(identity)
            self._heartbeat()
            return
        identity.registered = True
        if identity is self._identity:
            self._registered.set()

        reap_dead_servers(self.redis, dead)

        # A draining id with no take left on it can't get anything on its list
        # anymore: make sure its list was reaped, then delete its tombstone.
        with self._identity_lock:
            idle = [old for old in self._draining if old.active_takes == 0]
            for old in idle:
                self._draining.remove(old)
        for old in idle:
            reap_dead_servers(self.redis, [old.server_id])
            self.redis.drop_tombstone(old.processing_key)

    def _drain(self, old: _Identity) -> None:
        """Drain an id this server was declared dead under, which never
        heartbeats again, and carry on under a new one. The requests taken
        under the draining id are failed back by reapers, so the ones still
        running here finish with their results discarded, holding their
        concurrency slots until then.

        Called by the heartbeat when Redis refuses it, or by a read loop whose
        take hit the id's tombstone; whichever comes first drains, the other
        finds the id already switched. Read loops wait until the new id's
        first heartbeat, which this wakes at once."""
        with self._identity_lock:
            if self._identity is not old:
                return
            fresh = _Identity()
            self._identity = fresh
            self._draining.append(old)
            self._registered.clear()
        self._heartbeat_wake.set()
        logger.warning(
            f"Server {old.server_id} was declared dead (no heartbeat for over "
            f"{HEARTBEAT_TTL_SECONDS}s): draining it and continuing as {fresh.server_id}; "
            f"the requests it had taken are failed back to their clients, and their "
            f"results discarded"
        )

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
            with self._identity_lock:
                taker = self._identity
                if taker.registered:
                    taker.active_takes += 1
            if not taker.registered:
                # Just drained: wait for the new id's first heartbeat.
                limiter.release()
                self._registered.wait(TAKE_BLOCK_SECONDS)
                continue
            try:
                item = self.redis.take(queue_key, taker.processing_key, TAKE_BLOCK_SECONDS)
            except redis.exceptions.ResponseError as e:
                limiter.release()
                if "WRONGTYPE" in str(e):
                    # Our list is a tombstone: this id was reaped, so it's dead.
                    # The request stays in its queue.
                    self._drain(taker)
                elif self._running:
                    logger.warning(f"Error reading from queue {queue_key}: {e}")
                    time.sleep(1)
                continue
            except Exception as e:
                limiter.release()
                if self._running:
                    logger.warning(f"Error reading from queue {queue_key}: {e}")
                    time.sleep(1)
                continue
            finally:
                with self._identity_lock:
                    taker.active_takes -= 1
            if item is None:
                limiter.release()
                continue

            # Waits for a server-wide slot here, not before taking: see the
            # class docstring. The request is already on the processing list.
            if self._global_limiter is not None:
                self._global_limiter.acquire()
            try:
                self._executor.submit(self._process_message, item, handler, limiter, taker)
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

    def _process_message(
        self, item: str, handler: MethodHandler, method_limiter: ConcurrencyLimiter, taker: _Identity
    ) -> None:
        try:
            self._process_request(handler, item, taker)
        except Exception as e:
            logger.exception(f"Error processing request: {e}")
        finally:
            self._release_slots(method_limiter)

    def _process_request(self, handler: MethodHandler, item: str, taker: _Identity) -> None:
        """Process a single request and send response.

        `item` is the request json exactly as it was taken onto the processing
        list; it's removed from there along with sending the response, even if
        the request fails to deserialize here.

        A request the strict read rejects still gets its error, as long as its
        `requestId` and `clientId` can be read on their own. One without them
        has nowhere to be answered: it's dropped from the processing list, and
        nothing is answered.

        `taker` is the identity it was taken under. If it's draining by the
        time the request is done, reapers fail the request back, so its result
        is discarded and the old list left to them.
        """
        request_id = None
        client_id = None
        try:
            rpc_request = deserialize(item, AnyCallRequest)
            request_id = rpc_request.request_id
            client_id = rpc_request.client_id
            with self._in_flight_lock:
                self._in_flight_request_ids.add(request_id)

            param = deserialize(rpc_request.payload, handler.parameter_type)

            ctx = AnycallContext(request_id=rpc_request.request_id, method_name=rpc_request.method_name)
            result = handler.method(ctx, param)

            result_json = serialize(result)
            response = AnyCallResponse.success(rpc_request.request_id, result_json)

        except Exception as e:
            if request_id is None or client_id is None:
                address = read_reply_address(item)
                if address is None:
                    logger.warning(f"Dropped a request with no readable requestId or clientId: {e}")
                    if taker is self._identity:
                        self.redis.release(taker.processing_key, item)
                    return
                request_id, client_id = address
            logger.exception(f"Error invoking method: {e}")
            response = AnyCallResponse.error(request_id, str(e))
        finally:
            if request_id is not None:
                with self._in_flight_lock:
                    self._in_flight_request_ids.discard(request_id)

        if taker is not self._identity:
            logger.debug(
                f"Discarded the result of request {response.request_id}, taken under "
                f"draining id {taker.server_id}"
            )
            return
        response_queue = queues.response_queue(client_id)
        response_json = serialize(response)
        self.redis.respond(
            response_queue, response_json, queues.RESPONSE_TTL_SECONDS, taker.processing_key, item
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
