package dev.kaiquebt.anycall.server;

import com.fasterxml.jackson.databind.ObjectMapper;
import dev.kaiquebt.anycall.annotation.Supply;
import dev.kaiquebt.anycall.core.AnyCallServer;
import dev.kaiquebt.anycall.core.AnycallContext;
import dev.kaiquebt.anycall.model.AnyCallRequest;
import dev.kaiquebt.anycall.model.AnyCallResponse;
import dev.kaiquebt.anycall.publisher.AnycallQueues;
import dev.kaiquebt.anycall.publisher.AnycallReaping;
import dev.kaiquebt.anycall.publisher.AnycallResponses;
import io.lettuce.core.RedisClient;
import io.lettuce.core.RedisFuture;
import io.lettuce.core.ScriptOutputType;
import io.lettuce.core.api.StatefulRedisConnection;
import io.lettuce.core.api.async.RedisAsyncCommands;
import io.lettuce.core.api.sync.RedisCommands;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.lang.reflect.Method;
import java.time.Duration;
import java.util.ArrayList;
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
 * Every registered method gets a read loop of its own, which takes its requests with one
 * {@code BRPOPLPUSH}: the request moves from the method's queue onto this server's
 * processing list ({@code anycall:processing:<server id>}) in one atomic step, so a crash
 * at any point leaves it either still queued or on the list of the server that had it —
 * never neither. {@code BRPOPLPUSH} blocks, so an idle loop waits in Redis and is handed a
 * request the moment a client pushes one, and of several idle servers, Redis hands it to
 * exactly one.
 * <p>
 * A loop only asks for its next request when its method has a free {@code maxConcurrency}
 * permit, so requests for a busy method stay in their queue. The server-wide
 * {@code maxConcurrency}, if set, gates running a request rather than taking it: a loop
 * blocked in Redis can't hold a server-wide permit without starving the other methods, so
 * a request taken while every permit is busy waits here for one, already safe on the
 * processing list. That overshoots the cap on taking by at most one request per method.
 * <p>
 * Every heartbeat tick also fails back the requests of servers that stopped heartbeating
 * (see {@link AnycallReaping}): their clients get a {@code ServerLostError} instead of
 * waiting out their whole timeout.
 * <p>
 * {@code BRPOPLPUSH} reads a single queue and holds its connection while it blocks, so the
 * server uses one Redis connection per method, plus one shared by response writes and the
 * heartbeat.
 */
public class AnyCallServerImpl implements AnyCallServer {

    private static final Logger log = LoggerFactory.getLogger(AnyCallServerImpl.class);
    // How long a method's read loop blocks on its queue before looking again. Bounds how
    // long stop() and unregister() take to reach an idle loop; an idle loop costs one
    // command per this period.
    private static final long TAKE_BLOCK_SECONDS = 2;

    private static final String HEARTBEAT_KEY = AnycallQueues.HEARTBEAT_KEY;
    private static final Duration HEARTBEAT_PERIOD = Duration.ofSeconds(2);
    private static final Duration HEARTBEAT_TTL = AnycallQueues.HEARTBEAT_TTL;
    // KEYS[1] = live servers sorted set, ARGV[1] = server id, ARGV[2] = ttl seconds.
    // Returns {1 if this server's entry was missing (first tick, or it was reaped as
    // dead), followed by every member whose heartbeat is older than the ttl}. Prunes
    // nothing: a dead server leaves the set only through AnycallReaping's claim, so its
    // processing list is never forgotten.
    // Kept byte-for-byte identical to the Python server's copy.
    private static final String HEARTBEAT_SCRIPT = """
        local t = redis.call('TIME')
        local now = tonumber(t[1]) + tonumber(t[2]) / 1000000
        local added = redis.call('ZADD', KEYS[1], string.format('%.6f', now), ARGV[1])
        local result = redis.call('ZRANGEBYSCORE', KEYS[1], '-inf', '(' .. string.format('%.6f', now - tonumber(ARGV[2])))
        table.insert(result, 1, added)
        return result
        """;

    private static final ObjectMapper OBJECT_MAPPER = new ObjectMapper();

    private final RedisClient redisClient;
    private final StatefulRedisConnection<String, String> writeConnection;
    private final RedisCommands<String, String> writeCommands;
    // The write connection's async view, so a tick can give up after one period.
    private final RedisAsyncCommands<String, String> heartbeatCommands;
    private volatile boolean heartbeatRegistered;

    private final Map<String, MethodHandler> methodHandlers;
    private final Map<String, Semaphore> methodConcurrencyLimiters;
    private final Set<String> inFlightRequestIds;
    private final AtomicBoolean running;
    private final Semaphore globalConcurrencyLimiter;
    private final String serverId;
    private final String processingKey;
    // Read loops and the heartbeat, apart from the workers so stop() can wait for every
    // loop to exit before the worker pool stops taking requests.
    private ExecutorService loops;
    private ExecutorService workers;

    public AnyCallServerImpl(String redisUri) {
        this(redisUri, null);
    }

    /**
     * @param maxConcurrency server-wide cap on how many requests may be processed at
     *                       the same time, across every registered method combined
     *                       (see {@link dev.kaiquebt.anycall.annotation.Supply#maxConcurrency()});
     *                       {@code null} means uncapped — the sum of each method's own
     *                       {@code maxConcurrency} applies instead
     */
    public AnyCallServerImpl(String redisUri, Integer maxConcurrency) {
        if (redisUri == null || redisUri.isEmpty()) {
            throw new IllegalArgumentException("AnyCall Server: redisUri must not be null or blank");
        }
        if (maxConcurrency != null && maxConcurrency < 1) {
            throw new IllegalArgumentException("AnyCall Server: maxConcurrency must be at least 1");
        }
        this.redisClient = RedisClient.create(redisUri);
        this.writeConnection = redisClient.connect();
        this.writeCommands = writeConnection.sync();
        this.heartbeatCommands = writeConnection.async();
        this.methodHandlers = new ConcurrentHashMap<>();
        this.methodConcurrencyLimiters = new ConcurrentHashMap<>();
        this.inFlightRequestIds = ConcurrentHashMap.newKeySet();
        this.running = new AtomicBoolean(false);
        this.globalConcurrencyLimiter = maxConcurrency != null ? new Semaphore(maxConcurrency) : null;
        this.serverId = UUID.randomUUID().toString();
        this.processingKey = AnycallQueues.PROCESSING_PREFIX + serverId;
    }

    /**
     * Starts the server and begins processing incoming requests from Redis.
     * Spawns one read loop per registered method, the heartbeat, and the worker pool
     * that processes taken requests. This method is idempotent - repeated calls have no
     * effect if already running.
     *
     * @return this server instance for method chaining
     */
    @Override
    public synchronized AnyCallServer start() {
        if (running.compareAndSet(false, true)) {
            log.info("Starting AnyCall server {}", serverId);
            // Heartbeat once before taking any request: a server missing from the live set
            // is never looked at by reaping, so this server must be in it before its
            // processing list holds anything.
            heartbeatTick();
            loops = Executors.newCachedThreadPool();
            workers = Executors.newCachedThreadPool();
            loops.submit(this::emitHeartbeats);
            for (Map.Entry<String, MethodHandler> entry : methodHandlers.entrySet()) {
                startReader(entry.getKey(), entry.getValue());
            }
        }
        return this;
    }

    private void startReader(String methodName, MethodHandler handler) {
        loops.submit(() -> readMethod(methodName, handler));
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
     * Unregisters a method. Its read loop exits within {@link #TAKE_BLOCK_SECONDS}; a
     * request it takes in the meantime is still run and answered.
     */
    public synchronized AnyCallServer unregister(String methodName) {
        MethodHandler removed = methodHandlers.remove(methodName);
        if (removed != null) {
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

                MethodHandler handler = new MethodHandler(supplier, method, parameterType, maxConcurrency);
                synchronized (this) {
                    methodConcurrencyLimiters.put(methodName, new Semaphore(maxConcurrency));
                    // Replacing a handler makes the old one's loop exit on its next
                    // iteration; the new one gets a loop of its own.
                    methodHandlers.put(methodName, handler);
                    if (running.get()) {
                        startReader(methodName, handler);
                    }
                }
                log.debug("Registered supplier method: {} (maxConcurrency={})", methodName, maxConcurrency);
            }
        }
    }

    /**
     * Stops the server. Read loops notice within {@link #TAKE_BLOCK_SECONDS}; the requests
     * already taken get up to 5s more to finish and be answered.
     * This method is idempotent - repeated calls have no effect if already stopped.
     */
    @Override
    public void stop() {
        synchronized (this) {
            if (!running.compareAndSet(true, false)) {
                return;
            }
        }
        log.info("Stopping AnyCall server");
        try {
            loops.shutdown();
            if (!loops.awaitTermination(TAKE_BLOCK_SECONDS + 3, TimeUnit.SECONDS)) {
                loops.shutdownNow();
            }
            workers.shutdown();
            if (!workers.awaitTermination(5, TimeUnit.SECONDS)) {
                workers.shutdownNow();
            }
        } catch (InterruptedException e) {
            loops.shutdownNow();
            workers.shutdownNow();
            Thread.currentThread().interrupt();
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
     * Keeps this server's entry in the {@link #HEARTBEAT_KEY} sorted set fresh, so clients
     * and external tooling can tell it's alive by reading back the members scored within
     * {@link #HEARTBEAT_TTL} of Redis's current time ({@code TIME}).
     * <p>
     * Runs on its own thread so a slow or unreachable Redis never delays the read loops. It
     * shares the write connection: a tick is one command, so at worst it waits behind a
     * few response writes, never behind a handler. {@link #start} already ran the first
     * tick, so this one sleeps first.
     */
    private void emitHeartbeats() {
        try {
            while (running.get()) {
                Thread.sleep(HEARTBEAT_PERIOD.toMillis());
                if (running.get()) {
                    heartbeatTick();
                }
            }
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
        }
    }

    /**
     * One heartbeat, as a single {@code EVAL} of {@link #HEARTBEAT_SCRIPT}: {@code ZADD} this
     * server under Redis's own clock ({@code TIME}) and read back the servers whose heartbeat
     * is older than {@link #HEARTBEAT_TTL}, then fail back whatever those were still
     * processing.
     * <p>
     * "Now" is Redis's clock, not this host's, so scores written and compared by different
     * servers are always on the same clock — skew between hosts can't make a live server
     * look dead or a dead one alive.
     */
    private void heartbeatTick() {
        List<Object> result;
        try {
            RedisFuture<List<Object>> future = heartbeatCommands.eval(HEARTBEAT_SCRIPT, ScriptOutputType.MULTI,
                new String[] {HEARTBEAT_KEY}, serverId, String.valueOf(HEARTBEAT_TTL.getSeconds()));
            result = future.get(HEARTBEAT_PERIOD.toMillis(), TimeUnit.MILLISECONDS);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            return;
        } catch (TimeoutException e) {
            log.warn("Failed to write heartbeat: timed out after {}ms", HEARTBEAT_PERIOD.toMillis());
            return;
        } catch (Exception e) {
            log.warn("Failed to write heartbeat: {}", e.getMessage());
            return;
        }

        if (Long.valueOf(1).equals(result.get(0)) && heartbeatRegistered) {
            log.warn("Server {} was reaped as dead (no heartbeat for over {}s); the requests it "
                + "was processing have been failed back to their clients",
                serverId, HEARTBEAT_TTL.getSeconds());
        }
        heartbeatRegistered = true;

        List<String> dead = new ArrayList<>(result.size() - 1);
        for (Object member : result.subList(1, result.size())) {
            dead.add((String) member);
        }
        AnycallReaping.reapDeadServers(writeCommands, dead);
    }

    /**
     * Read loop for one method's queue, until the server stops or the method is
     * unregistered (or registered again, which starts a new loop). Waits for a free
     * permit of the method before every take, so it never takes a request it has no room
     * to run. Holds a connection of its own, since {@code BRPOPLPUSH} blocks it.
     */
    private void readMethod(String methodName, MethodHandler handler) {
        String queueKey = AnycallQueues.REQUEST_QUEUE_PREFIX + methodName;
        Semaphore methodLimiter = methodConcurrencyLimiters.get(methodName);
        log.info("Started reading queue {}", queueKey);

        while (isCurrent(methodName, handler)) {
            try (StatefulRedisConnection<String, String> connection = redisClient.connect()) {
                RedisCommands<String, String> commands = connection.sync();
                while (isCurrent(methodName, handler)) {
                    if (!methodLimiter.tryAcquire(TAKE_BLOCK_SECONDS, TimeUnit.SECONDS)) {
                        continue;
                    }
                    String item;
                    try {
                        item = commands.brpoplpush(TAKE_BLOCK_SECONDS, queueKey, processingKey);
                    } catch (RuntimeException e) {
                        methodLimiter.release();
                        throw e;
                    }
                    if (item == null) {
                        methodLimiter.release();
                        continue;
                    }
                    dispatch(item, handler, methodLimiter);
                }
            } catch (InterruptedException e) {
                // Only from shutdownNow(): whatever was taken stays on the processing list,
                // to be failed back once this server stops heartbeating.
                Thread.currentThread().interrupt();
                return;
            } catch (Exception e) {
                if (!running.get()) {
                    return;
                }
                log.error("Error reading from queue {}: {}", queueKey, e.getMessage());
                try {
                    Thread.sleep(1000);
                } catch (InterruptedException ie) {
                    Thread.currentThread().interrupt();
                    return;
                }
            }
        }
    }

    private boolean isCurrent(String methodName, MethodHandler handler) {
        return running.get() && methodHandlers.get(methodName) == handler;
    }

    /**
     * Hands a taken request to the worker pool. Waits for a server-wide permit first, if
     * there's a cap: see the class docs for why that happens after taking, not before.
     */
    private void dispatch(String item, MethodHandler handler, Semaphore methodLimiter) throws InterruptedException {
        if (globalConcurrencyLimiter != null) {
            try {
                globalConcurrencyLimiter.acquire();
            } catch (InterruptedException e) {
                methodLimiter.release();
                throw e;
            }
        }
        workers.submit(() -> {
            try {
                processRequest(item, handler);
            } finally {
                if (globalConcurrencyLimiter != null) {
                    globalConcurrencyLimiter.release();
                }
                methodLimiter.release();
            }
        });
    }

    /**
     * Processes a single request by deserializing it, invoking the handler method, and sending the response.
     * Handles errors gracefully and sends error responses back to the client.
     *
     * @param requestJson the JSON-serialized request, exactly as it was taken onto the
     *                    processing list; removed from there along with the response
     * @param handler the method handler to invoke
     */
    private void processRequest(String requestJson, MethodHandler handler) {
        String requestId = null;
        String methodName = null;

        try {
            AnyCallRequest request = OBJECT_MAPPER.readValue(requestJson, AnyCallRequest.class);
            requestId = request.requestId();
            methodName = request.methodName();
            inFlightRequestIds.add(requestId);

            log.debug("Processing request: {} for method: {}", requestId, methodName);

            Object parameter = OBJECT_MAPPER.readValue(request.payload(), handler.parameterType());

            AnycallContext ctx = new AnycallContext(requestId, methodName);
            Object result = handler.method().invoke(handler.bean(), ctx, parameter);

            String resultJson = OBJECT_MAPPER.writeValueAsString(result);

            AnyCallResponse response = AnyCallResponse.success(requestId, resultJson);
            sendResponse(response, requestJson);

            log.debug("Request {} processed successfully", requestId);
        } catch (Exception e) {
            log.error("Error processing request: {}", requestId, e);
            AnyCallResponse response = AnyCallResponse.error(
                requestId != null ? requestId : "unknown",
                e.getMessage() != null ? e.getMessage() : e.getClass().getName()
            );
            sendResponse(response, requestJson);
        } finally {
            if (requestId != null) {
                inFlightRequestIds.remove(requestId);
            }
        }
    }

    /**
     * Sends a response back to the client and drops its request from this server's
     * processing list, in one script: the push runs first, so if it never happens the
     * request is still on the list to be failed back.
     *
     * @param response the response to send
     * @param requestJson the request json exactly as it was taken
     */
    private void sendResponse(AnyCallResponse response, String requestJson) {
        try {
            AnycallResponses.pushAndRelease(writeCommands, response, processingKey, requestJson);
        } catch (Exception e) {
            log.error("Error sending response: {}", response.requestId(), e);
        }
    }
}
