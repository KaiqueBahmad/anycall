package dev.kaiquebt.anycall.server;

import com.fasterxml.jackson.databind.ObjectMapper;
import dev.kaiquebt.anycall.annotation.Supply;
import dev.kaiquebt.anycall.core.AnyCallServer;
import dev.kaiquebt.anycall.core.AnycallContext;
import dev.kaiquebt.anycall.model.AnyCallRequest;
import dev.kaiquebt.anycall.model.AnyCallResponse;
import dev.kaiquebt.anycall.publisher.AnycallQueues;
import dev.kaiquebt.anycall.publisher.AnycallResponses;
import io.lettuce.core.RedisClient;
import io.lettuce.core.RedisFuture;
import io.lettuce.core.ScriptOutputType;
import io.lettuce.core.api.StatefulRedisConnection;
import io.lettuce.core.api.async.RedisAsyncCommands;
import io.lettuce.core.api.sync.RedisCommands;
import io.lettuce.core.pubsub.RedisPubSubAdapter;
import io.lettuce.core.pubsub.StatefulRedisPubSubConnection;
import io.lettuce.core.pubsub.api.sync.RedisPubSubCommands;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.lang.reflect.Method;
import java.time.Duration;
import java.util.ArrayList;
import java.util.Collections;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Semaphore;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.TimeoutException;
import java.util.concurrent.atomic.AtomicBoolean;

/**
 * Internal implementation of AnyCallServer.
 * <p>
 * <strong>This class is not intended for direct use. Use {@link dev.kaiquebt.anycall.core.AnyCall#server(String)} instead.</strong>
 * </p>
 * One read loop takes requests off every registered method's queue and dispatches them
 * to a shared worker pool. Each take runs {@link #ACQUIRE_SCRIPT}, which pops the request
 * and records this server as its owner in {@link AnycallQueues#INFLIGHT_KEY} in one
 * atomic step, so a crash at any point leaves either the request still queued or a
 * record of who had it — never neither.
 * <p>
 * A script can't block, so the loop doesn't either: when there's nothing to take it
 * waits on {@link #doorbell}, released by a wake message for one of its methods (clients
 * publish on {@code anycall:wake:<method>} after every push), by a worker freeing a slot,
 * or after {@link #WAKE_FALLBACK} regardless. It always tries its queues before waiting,
 * so requests already queued at startup or after a busy spell are picked up without
 * needing a wake.
 * <p>
 * Every heartbeat tick also fails back the in-flight requests of servers that stopped
 * heartbeating (see {@link #reapOrphans}): their clients get a {@code ServerLostError}
 * instead of waiting out their whole timeout.
 * <p>
 * The whole server uses exactly four Redis connections — one for taking requests, one
 * shared for response writes, one dedicated to the heartbeat, and one held by the wake
 * subscription — no matter how many methods or how much concurrency is configured.
 */
public class AnyCallServerImpl implements AnyCallServer {

    private static final Logger log = LoggerFactory.getLogger(AnyCallServerImpl.class);
    // How long the read loop waits for a wake (or a freed slot) before looking at its
    // queues anyway — the safety net for a wake missed during a reconnect, or published
    // by a client that predates wakes.
    private static final Duration WAKE_FALLBACK = Duration.ofSeconds(1);
    private static final String INFLIGHT_KEY = AnycallQueues.INFLIGHT_KEY;

    private static final String HEARTBEAT_KEY = AnycallQueues.HEARTBEAT_KEY;
    private static final Duration HEARTBEAT_PERIOD = Duration.ofSeconds(2);
    private static final Duration HEARTBEAT_TTL = AnycallQueues.HEARTBEAT_TTL;
    // KEYS[1] = live servers sorted set, ARGV[1] = server id, ARGV[2] = ttl seconds.
    // Returns {1 if this server's entry was missing (first tick, or it was pruned as
    // dead), followed by every member still alive after the prune}.
    // Kept byte-for-byte identical to the Python server's copy.
    private static final String HEARTBEAT_SCRIPT = """
        local t = redis.call('TIME')
        local now = tonumber(t[1]) + tonumber(t[2]) / 1000000
        local added = redis.call('ZADD', KEYS[1], string.format('%.6f', now), ARGV[1])
        redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', string.format('%.6f', now - tonumber(ARGV[2])))
        redis.call('EXPIRE', KEYS[1], ARGV[2])
        local result = redis.call('ZRANGE', KEYS[1], 0, -1)
        table.insert(result, 1, added)
        return result
        """;

    // KEYS[1] = in-flight hash, KEYS[2..n] = request queues to try, in order.
    // ARGV[1] = server id. Returns {queue, request json, request id} for the first queue
    // with an entry, or {} if all were empty. The request id is '' if the entry isn't a
    // parseable request — then it isn't recorded as in flight.
    // Kept byte-for-byte identical to the Python server's copy.
    private static final String ACQUIRE_SCRIPT = """
        for i = 2, #KEYS do
          local item = redis.call('RPOP', KEYS[i])
          if item then
            local ok, request = pcall(cjson.decode, item)
            local id = ''
            if ok and type(request) == 'table' and type(request.requestId) == 'string' then
              id = request.requestId
              redis.call('HSET', KEYS[1], id, ARGV[1])
            end
            return {KEYS[i], item, id}
          end
        end
        return {}
        """;

    private static final ObjectMapper OBJECT_MAPPER = new ObjectMapper();

    private final RedisClient redisClient;
    private final StatefulRedisConnection<String, String> readConnection;
    private final RedisCommands<String, String> readCommands;
    private final StatefulRedisConnection<String, String> writeConnection;
    private final RedisCommands<String, String> writeCommands;
    private final StatefulRedisConnection<String, String> heartbeatConnection;
    private final RedisAsyncCommands<String, String> heartbeatCommands;
    private final StatefulRedisPubSubConnection<String, String> wakeConnection;
    private final RedisPubSubCommands<String, String> wakeCommands;
    private final Set<String> wakeChannels;

    /**
     * Tells the read loop to look at its queues again: a wake arrived for one of its
     * methods, a local slot freed up, or the method set changed. Used as a doorbell, not
     * a counter — the loop drains every permit before looking, so a release that lands
     * while it looks is kept and its next wait returns straight away.
     */
    private final Semaphore doorbell;
    private volatile boolean heartbeatRegistered;

    private final Map<String, MethodHandler> methodHandlers;
    private final Map<String, Semaphore> methodConcurrencyLimiters;
    private final Set<String> inFlightRequestIds;
    private final AtomicBoolean running;
    private final boolean metricsEnabled;
    private final Semaphore globalConcurrencyLimiter;
    private final String serverId;
    private ExecutorService executor;

    public AnyCallServerImpl(String redisUri, boolean metricsEnabled) {
        this(redisUri, metricsEnabled, null);
    }

    /**
     * @param maxConcurrency server-wide cap on how many requests may be processed at
     *                       the same time, across every registered method combined
     *                       (see {@link dev.kaiquebt.anycall.annotation.Supply#maxConcurrency()});
     *                       {@code null} means uncapped — the sum of each method's own
     *                       {@code maxConcurrency} applies instead
     */
    public AnyCallServerImpl(String redisUri, boolean metricsEnabled, Integer maxConcurrency) {
        if (redisUri == null || redisUri.isEmpty()) {
            throw new IllegalArgumentException("AnyCall Server: redisUri must not be null or blank");
        }
        if (maxConcurrency != null && maxConcurrency < 1) {
            throw new IllegalArgumentException("AnyCall Server: maxConcurrency must be at least 1");
        }
        this.redisClient = RedisClient.create(redisUri);
        this.readConnection = redisClient.connect();
        this.readCommands = readConnection.sync();
        this.writeConnection = redisClient.connect();
        this.writeCommands = writeConnection.sync();
        this.heartbeatConnection = redisClient.connect();
        this.heartbeatCommands = heartbeatConnection.async();
        this.wakeConnection = redisClient.connectPubSub();
        this.wakeCommands = wakeConnection.sync();
        this.wakeChannels = new HashSet<>();
        this.doorbell = new Semaphore(0);
        // Any wake rings the doorbell; which channel it came from doesn't matter, the
        // read loop tries every method with capacity anyway.
        wakeConnection.addListener(new RedisPubSubAdapter<>() {
            @Override
            public void message(String channel, String message) {
                doorbell.release();
            }
        });
        this.methodHandlers = new ConcurrentHashMap<>();
        this.methodConcurrencyLimiters = new ConcurrentHashMap<>();
        this.inFlightRequestIds = ConcurrentHashMap.newKeySet();
        this.running = new AtomicBoolean(false);
        this.metricsEnabled = metricsEnabled;
        this.globalConcurrencyLimiter = maxConcurrency != null ? new Semaphore(maxConcurrency) : null;
        this.serverId = UUID.randomUUID().toString();
    }

    /**
     * Starts the server and begins processing incoming requests from Redis.
     * Spawns the single read loop plus the worker pool that processes dispatched
     * requests. This method is idempotent - repeated calls have no effect if already
     * running.
     *
     * @return this server instance for method chaining
     */
    @Override
    public AnyCallServer start() {
        if (running.compareAndSet(false, true)) {
            log.info("Starting AnyCall server {}", serverId);
            // Heartbeat once before taking any request: another server's cleanup treats
            // an in-flight owner missing from the live set as dead, so this server must
            // be in it before it owns anything.
            heartbeatTick();
            executor = Executors.newCachedThreadPool();
            executor.submit(this::pollAllQueues);
            executor.submit(this::emitHeartbeats);
        }
        return this;
    }

    public AnyCallServer register(Object supplier) {
        scanAndRegisterSupplier(supplier);
        return this;
    }

    public AnyCallServer register(Object... suppliers) {
        for (Object supplier : suppliers) {
            scanAndRegisterSupplier(supplier);
        }
        return this;
    }

    /**
     * Unregisters a method. Takes effect on the read loop's next iteration, which also
     * drops its wake subscription — there's no per-method thread or connection to tear
     * down, since the whole server shares one reader and one writer connection.
     */
    public AnyCallServer unregister(String methodName) {
        MethodHandler removed = methodHandlers.remove(methodName);
        if (removed != null) {
            methodConcurrencyLimiters.remove(methodName);
            doorbell.release();
            log.info("Unregistered method: {}", methodName);
        }
        return this;
    }
    private void scanAndRegisterSupplier(Object supplier) {
        Class<?> supplierClass = supplier.getClass();

        for (Method method : supplierClass.getDeclaredMethods()) {
            Supply supplyAnnotation = method.getAnnotation(Supply.class);

            if (supplyAnnotation != null) {
                String methodName = supplyAnnotation.methodName();

                if (method.getParameterCount() != 2) {
                    throw new IllegalStateException(
                        "Method " + method.getName() + " annotated with @Supply must have exactly two parameters: "
                            + "(AnycallContext, <request type>)"
                    );
                }

                if (method.getParameterTypes()[0] != AnycallContext.class) {
                    throw new IllegalStateException(
                        "Method " + method.getName() + " annotated with @Supply must declare AnycallContext "
                            + "as its first parameter"
                    );
                }

                int maxConcurrency = supplyAnnotation.maxConcurrency();
                if (maxConcurrency < 1) {
                    throw new IllegalStateException(
                        "Method " + method.getName() + " annotated with @Supply has invalid maxConcurrency "
                            + maxConcurrency + "; it must be at least 1"
                    );
                }

                Class<?> parameterType = method.getParameterTypes()[1];
                method.setAccessible(true);

                methodHandlers.put(methodName, new MethodHandler(supplier, method, parameterType, maxConcurrency));
                methodConcurrencyLimiters.put(methodName, new Semaphore(maxConcurrency));
                doorbell.release();
                log.debug("Registered supplier method: {} (maxConcurrency={})", methodName, maxConcurrency);
            }
        }
    }

    /**
     * Stops the server and shuts down the read loop and worker pool.
     * Gracefully terminates the executor service with a timeout.
     * This method is idempotent - repeated calls have no effect if already stopped.
     */
    @Override
    public void stop() {
        if (running.compareAndSet(true, false)) {
            log.info("Stopping AnyCall server");
            doorbell.release();
            if (executor != null) {
                executor.shutdown();
                try {
                    if (!executor.awaitTermination(5, TimeUnit.SECONDS)) {
                        executor.shutdownNow();
                    }
                } catch (InterruptedException e) {
                    executor.shutdownNow();
                    Thread.currentThread().interrupt();
                }
            }
        }
    }

    /**
     * Checks if the server is currently running and processing requests.
     *
     * @return {@code true} if the server is running, {@code false} otherwise
     */
    @Override
    public boolean isRunning() {
        return running.get();
    }

    /**
     * Request IDs currently between deserialization and response in {@link #processRequest}.
     * A snapshot, not a live view — safe to iterate without external synchronization.
     */
    public Set<String> getInFlightRequestIds() {
        return Set.copyOf(inFlightRequestIds);
    }

    /**
     * This server instance's id — the member it registers under in {@code anycall:servers:alive}.
     * Generated at construction, stable for the instance's lifetime, and never reused
     * across restarts.
     *
     * @return this server's id
     */
    public String getServerId() {
        return serverId;
    }

    /**
     * Keeps this server's entry in the {@link #HEARTBEAT_KEY} sorted set fresh, so external
     * tooling can list live servers by reading back the members scored within
     * {@link #HEARTBEAT_TTL} of Redis's current time ({@code TIME}).
     * <p>
     * Runs on its own thread so a slow or unreachable Redis never delays
     * {@link #pollAllQueues} from draining its queues. {@link #start} already ran the
     * first tick, so this one sleeps first.
     */
    private void emitHeartbeats() {
        try {
            while (running.get()) {
                Thread.sleep(HEARTBEAT_PERIOD.toMillis());
                heartbeatTick();
            }
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
        }
    }

    /**
     * One heartbeat ({@link #writeHeartbeat}, which also prunes the entries that stopped
     * being refreshed), then fail back whatever the servers found dead were still
     * processing.
     */
    private void heartbeatTick() {
        Map<String, String> owners;
        HeartbeatResult heartbeat;
        try {
            // Read before the live set, never after: an owner must heartbeat before it
            // can take a request, so any owner in this snapshot was in the live set first,
            // and is missing from the one read below only if it really stopped heartbeating.
            owners = await(heartbeatCommands.hgetall(INFLIGHT_KEY));
            heartbeat = writeHeartbeat();
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            return;
        } catch (Exception e) {
            log.warn("Failed to write heartbeat: {}", e.getMessage());
            return;
        }

        if (heartbeat.rejoined() && heartbeatRegistered) {
            log.warn("Server {} was pruned as dead (no heartbeat for over {}s); the requests it "
                + "was processing may already have been failed back to their clients",
                serverId, HEARTBEAT_TTL.getSeconds());
        }
        heartbeatRegistered = true;

        reapOrphans(owners, heartbeat.alive());
    }

    /**
     * For each in-flight request whose owner isn't alive anymore, pushes an error to its
     * response queue so the client stops waiting.
     * <p>
     * Several live servers can notice the same dead owner on the same tick; the
     * {@code HDEL} is the claim — only the one that actually removes the entry writes the
     * error, so the client never gets two.
     */
    private void reapOrphans(Map<String, String> owners, Set<String> alive) {
        for (Map.Entry<String, String> entry : owners.entrySet()) {
            String requestId = entry.getKey();
            String owner = entry.getValue();
            if (alive.contains(owner)) {
                continue;
            }
            try {
                if (await(heartbeatCommands.hdel(INFLIGHT_KEY, requestId)) != 1) {
                    continue;
                }
                AnycallResponses.push(writeCommands, AnyCallResponse.serverLost(requestId, owner));
                log.warn("Failed request {} back to its client: server {} is gone", requestId, owner);
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
                return;
            } catch (Exception e) {
                log.warn("Failed to fail back request {} of dead server {}: {}", requestId, owner, e.getMessage());
            }
        }
    }

    private static <T> T await(RedisFuture<T> future) throws Exception {
        try {
            return future.get(HEARTBEAT_PERIOD.toMillis(), TimeUnit.MILLISECONDS);
        } catch (TimeoutException e) {
            throw new IllegalStateException("timed out after " + HEARTBEAT_PERIOD.toMillis() + "ms", e);
        }
    }

    private record HeartbeatResult(boolean rejoined, Set<String> alive) {
    }

    /**
     * One heartbeat tick, as a single {@code EVAL} of {@link #HEARTBEAT_SCRIPT}: {@code ZADD}
     * this server under the current time, {@code ZREMRANGEBYSCORE} to drop the members
     * that stopped being refreshed (servers that are gone), then refresh the key's TTL.
     * <p>
     * "Now" is Redis's own clock ({@code TIME}), not this host's, so scores written and
     * pruned by different servers are always compared on the same clock — skew between
     * hosts can't prune a live server or keep a dead one around. The script touches one
     * key, so it stays compatible with Redis Cluster.
     * <p>
     * Runs on its own connection ({@link #heartbeatConnection}) so it never stalls
     * {@link #sendResponse}, which shares {@link #writeCommands} with the worker threads.
     *
     * @return whether this server had no entry before this tick, and every live member
     */
    private HeartbeatResult writeHeartbeat() throws Exception {
        RedisFuture<List<Object>> future = heartbeatCommands.eval(HEARTBEAT_SCRIPT, ScriptOutputType.MULTI,
            new String[] {HEARTBEAT_KEY}, serverId, String.valueOf(HEARTBEAT_TTL.getSeconds()));
        List<Object> result = await(future);
        Set<String> alive = new HashSet<>();
        for (Object member : result.subList(1, result.size())) {
            alive.add((String) member);
        }
        return new HeartbeatResult(Long.valueOf(1).equals(result.get(0)), alive);
    }

    /**
     * Single read loop for every registered method's request queue. Only takes from
     * queues with spare {@code maxConcurrency} capacity (see {@link #methodsWithCapacity}),
     * so a saturated method's requests stay in Redis instead of piling up in memory.
     */
    private void pollAllQueues() {
        while (running.get()) {
            try {
                Map<String, MethodHandler> snapshot = new HashMap<>(methodHandlers);
                syncWakeSubscriptions(snapshot.keySet());

                Set<String> available = methodsWithCapacity(snapshot.keySet());
                if (available.isEmpty()) {
                    // Nothing registered, or every registered method (or the server-wide
                    // cap) is saturated: a worker finishing releases the doorbell, so wait
                    // for that instead of busy-looping.
                    waitForDoorbell();
                    continue;
                }

                // Drained before looking, not after: a wake that lands while the script
                // runs stays as a permit, so the wait below returns at once.
                doorbell.drainPermits();
                List<Object> acquired = readCommands.eval(ACQUIRE_SCRIPT, ScriptOutputType.MULTI,
                    buildAcquireKeys(available), serverId);
                if (acquired == null || acquired.isEmpty()) {
                    waitForDoorbell();
                    continue;
                }

                handleMessage((String) acquired.get(0), (String) acquired.get(1), (String) acquired.get(2), snapshot);
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
            } catch (Exception e) {
                if (running.get()) {
                    log.error("Error reading from queues: {}", e.getMessage());
                }
            }
        }
    }

    private void waitForDoorbell() throws InterruptedException {
        doorbell.tryAcquire(WAKE_FALLBACK.toMillis(), TimeUnit.MILLISECONDS);
        doorbell.drainPermits();
    }

    /**
     * Subscribes to the wake channel of every registered method and drops the ones no
     * longer registered. Called from the read loop, so runtime (un)registrations are
     * picked up on its next iteration. After a new subscription the doorbell is released,
     * since a request could have landed before the subscription existed.
     * <p>
     * A wake is only a hint, so losing one is harmless — the loop looks at its queues
     * every {@link #WAKE_FALLBACK} anyway. Lettuce resubscribes on its own after a
     * reconnect.
     */
    private void syncWakeSubscriptions(Set<String> methodNames) {
        Set<String> wanted = new HashSet<>();
        for (String methodName : methodNames) {
            wanted.add(AnycallQueues.WAKE_CHANNEL_PREFIX + methodName);
        }
        Set<String> added = new HashSet<>(wanted);
        added.removeAll(wakeChannels);
        Set<String> removed = new HashSet<>(wakeChannels);
        removed.removeAll(wanted);
        if (added.isEmpty() && removed.isEmpty()) {
            return;
        }
        if (!added.isEmpty()) {
            wakeCommands.subscribe(added.toArray(new String[0]));
            doorbell.release();
        }
        if (!removed.isEmpty()) {
            wakeCommands.unsubscribe(removed.toArray(new String[0]));
        }
        wakeChannels.clear();
        wakeChannels.addAll(wanted);
    }

    // TODO: review whole concurrency implementation
    /**
     * Methods with a free permit on both their own semaphore and the server-wide
     * one, if any. A point-in-time read, not a reservation, so it can be stale by
     * the time {@link #handleMessage} actually acquires — that's fine, worst case
     * one extra request gets taken just as its method fills up.
     */
    private Set<String> methodsWithCapacity(Set<String> methodNames) {
        if (globalConcurrencyLimiter != null && globalConcurrencyLimiter.availablePermits() <= 0) {
            return Set.of();
        }
        Set<String> available = new HashSet<>();
        for (String methodName : methodNames) {
            Semaphore limiter = methodConcurrencyLimiters.get(methodName);
            if (limiter == null || limiter.availablePermits() > 0) {
                available.add(methodName);
            }
        }
        return available;
    }

    /**
     * Builds the keys for {@link #ACQUIRE_SCRIPT}: the in-flight hash, then the request
     * queues to try, shuffled so that the script's preference for the first queue with
     * data doesn't starve a method that consistently sorts after a busier one in
     * {@code methodNames}' iteration order.
     */
    private String[] buildAcquireKeys(Set<String> methodNames) {
        List<String> queues = new ArrayList<>(methodNames.size());
        for (String methodName : methodNames) {
            queues.add(AnycallQueues.REQUEST_QUEUE_PREFIX + methodName);
        }
        Collections.shuffle(queues);
        List<String> keys = new ArrayList<>(queues.size() + 1);
        keys.add(INFLIGHT_KEY);
        keys.addAll(queues);
        return keys.toArray(new String[0]);
    }

    /**
     * Routes one taken request to its handler. Acquires both semaphores on this
     * (the poll loop's) thread, before dispatching — since {@link #methodsWithCapacity}
     * already filtered for availability, this is normally instant; it only actually
     * waits if that pre-filter's read is stale, which is exactly when the loop
     * should wait rather than take another request the method has no room for.
     *
     * @param queueKey the queue the request was taken from
     * @param requestJson the raw request JSON
     * @param acquiredId the id {@link #ACQUIRE_SCRIPT} recorded it under in the in-flight
     *                   hash, or {@code ""} if it couldn't parse one
     * @param snapshot the method registry as it was when this entry was read
     */
    private void handleMessage(String queueKey, String requestJson, String acquiredId,
                               Map<String, MethodHandler> snapshot) {
        String methodName = queueKey.substring(AnycallQueues.REQUEST_QUEUE_PREFIX.length());
        MethodHandler handler = snapshot.get(methodName);

        // TODO verify if this is really the expected behaviour
        if (handler == null) {
            // Unregistered between being taken and being routed; nothing left to hand
            // it to, so drop it along with its in-flight entry.
            log.warn("No handler registered for method '{}'; dropping request from queue {}",
                    methodName, queueKey);
            releaseInflight(acquiredId);
            return;
        }

        Semaphore methodLimiter = methodConcurrencyLimiters.get(methodName);
        boolean methodAcquired = false;
        boolean globalAcquired = false;
        try {
            if (methodLimiter != null) {
                methodLimiter.acquire();
                methodAcquired = true;
            }
            if (globalConcurrencyLimiter != null) {
                globalConcurrencyLimiter.acquire();
                globalAcquired = true;
            }
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            if (methodAcquired) {
                methodLimiter.release();
            }
            // Already out of its queue, so never getting to run the handler just
            // means it's lost — at-most-once, as before.
            releaseInflight(acquiredId);
            return;
        }

        boolean releaseGlobal = globalAcquired;
        boolean releaseMethod = methodAcquired;
        executor.submit(() -> {
            try {
                processRequest(requestJson, handler);
            } finally {
                releaseInflight(acquiredId);
                if (releaseGlobal) {
                    globalConcurrencyLimiter.release();
                }
                if (releaseMethod) {
                    methodLimiter.release();
                }
                // A slot just freed up: have the read loop look for more work now
                // rather than on its next fallback tick.
                doorbell.release();
            }
        });
    }

    /**
     * Processes a single request by deserializing it, invoking the handler method, and sending the response.
     * Handles errors gracefully and sends error responses back to the client.
     * Collects detailed metrics if metrics are enabled.
     *
     * @param requestJson the JSON-serialized request
     * @param handler the method handler to invoke
     */
    private void processRequest(String requestJson, MethodHandler handler) {
        long startTime = metricsEnabled ? System.currentTimeMillis() : 0;
        String requestId = null;
        String methodName = null;

        try {
            long beforeDeserialize = metricsEnabled ? System.currentTimeMillis() : 0;
            AnyCallRequest request = OBJECT_MAPPER.readValue(requestJson, AnyCallRequest.class);
            requestId = request.requestId();
            methodName = request.methodName();
            inFlightRequestIds.add(requestId);

            if (metricsEnabled) {
                log.debug("[METRICS] [SERVER] [{}] Request deserialized in {}ms", requestId,
                    System.currentTimeMillis() - beforeDeserialize);
            } else {
                log.debug("Processing request: {} for method: {}", requestId, methodName);
            }

            long beforePayloadDeserialize = metricsEnabled ? System.currentTimeMillis() : 0;
            Object parameter = OBJECT_MAPPER.readValue(request.payload(), handler.parameterType());

            if (metricsEnabled) {
                log.debug("[METRICS] [SERVER] [{}] Payload deserialized in {}ms", requestId,
                    System.currentTimeMillis() - beforePayloadDeserialize);
            }

            long beforeInvoke = metricsEnabled ? System.currentTimeMillis() : 0;
            AnycallContext ctx = new AnycallContext(requestId, methodName);
            Object result = handler.method().invoke(handler.bean(), ctx, parameter);

            if (metricsEnabled) {
                log.debug("[METRICS] [SERVER] [{}] Method '{}' executed in {}ms", requestId, methodName,
                    System.currentTimeMillis() - beforeInvoke);
            }

            long beforeSerialize = metricsEnabled ? System.currentTimeMillis() : 0;
            String resultJson = OBJECT_MAPPER.writeValueAsString(result);

            if (metricsEnabled) {
                log.debug("[METRICS] [SERVER] [{}] Result serialized in {}ms", requestId,
                    System.currentTimeMillis() - beforeSerialize);
            }

            long beforeSend = metricsEnabled ? System.currentTimeMillis() : 0;
            AnyCallResponse response = AnyCallResponse.success(requestId, resultJson);
            sendResponse(response);

            if (metricsEnabled) {
                log.debug("[METRICS] [SERVER] [{}] Response sent in {}ms", requestId,
                    System.currentTimeMillis() - beforeSend);
                log.debug("[METRICS] [SERVER] [{}] Total processing time: {}ms", requestId,
                    System.currentTimeMillis() - startTime);
            } else {
                log.debug("Request {} processed successfully", requestId);
            }

        } catch (Exception e) {
            if (metricsEnabled && requestId != null) {
                log.error("[METRICS] [SERVER] [{}] Processing failed after {}ms: {}", requestId,
                    System.currentTimeMillis() - startTime, e.getMessage());
            }
            log.error("Error processing request: {}", requestId, e);
            if (requestId != null) {
                AnyCallResponse response = AnyCallResponse.error(
                    requestId,
                    e.getMessage() != null ? e.getMessage() : e.getClass().getName()
                );
                sendResponse(response);
            }
        } finally {
            if (requestId != null) {
                inFlightRequestIds.remove(requestId);
            }
        }
    }

    /**
     * Drops a request's in-flight entry. Runs after its response is sent, never before:
     * if the process dies in between, the entry is failed back as a crash, but the client
     * pops the real response before that error ({@code BRPOP} takes the oldest).
     *
     * @param acquiredId the id the request was taken under; {@code ""} means none
     */
    private void releaseInflight(String acquiredId) {
        if (acquiredId == null || acquiredId.isEmpty()) {
            return;
        }
        try {
            writeCommands.hdel(INFLIGHT_KEY, acquiredId);
        } catch (Exception e) {
            log.warn("Failed to drop in-flight entry for request {}: {}", acquiredId, e.getMessage());
        }
    }

    /**
     * Sends a response back to the client via a Redis queue.
     * Serializes the response and pushes it to the client's response queue.
     *
     * @param response the response to send
     */
    private void sendResponse(AnyCallResponse response) {
        try {
            AnycallResponses.push(writeCommands, response);
        } catch (Exception e) {
            log.error("Error sending response: {}", response.requestId(), e);
        }
    }
}
