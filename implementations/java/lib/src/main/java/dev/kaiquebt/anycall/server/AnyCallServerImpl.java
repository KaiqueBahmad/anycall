package dev.kaiquebt.anycall.server;

import com.fasterxml.jackson.databind.ObjectMapper;
import dev.kaiquebt.anycall.core.AnyCallServer;
import dev.kaiquebt.anycall.core.AnycallContext;
import dev.kaiquebt.anycall.core.MethodInfo;
import dev.kaiquebt.anycall.core.ServerOptions;
import dev.kaiquebt.anycall.core.SupplyHandler;
import dev.kaiquebt.anycall.core.SupplyMethod;
import dev.kaiquebt.anycall.exception.AnyCallError;
import dev.kaiquebt.anycall.model.AnyCallRequest;
import dev.kaiquebt.anycall.model.AnyCallResponse;
import dev.kaiquebt.anycall.publisher.AnycallQueues;
import dev.kaiquebt.anycall.publisher.AnycallReaping;
import dev.kaiquebt.anycall.publisher.AnycallResponses;
import io.lettuce.core.ClientOptions;
import io.lettuce.core.LMoveArgs;
import io.lettuce.core.RedisClient;
import io.lettuce.core.RedisCommandExecutionException;
import io.lettuce.core.protocol.ProtocolVersion;
import io.lettuce.core.RedisFuture;
import io.lettuce.core.ScriptOutputType;
import io.lettuce.core.api.StatefulRedisConnection;
import io.lettuce.core.api.async.RedisAsyncCommands;
import io.lettuce.core.api.sync.RedisCommands;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.time.Duration;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Semaphore;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.TimeoutException;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicInteger;

/**
 * Internal implementation of AnyCallServer.
 * <p>
 * <strong>This class is not intended for direct use. Use {@link dev.kaiquebt.anycall.core.AnyCall#server(String)} instead.</strong>
 * </p>
 * Every registered method gets a read loop of its own, which takes its requests with one
 * {@code BLMOVE} ({@code BRPOPLPUSH} on a Redis before 6.2): the request moves from the method's queue onto this server's
 * processing list ({@code anycall:processing:<server id>}) in one atomic step, so a crash
 * at any point leaves it either still queued or on the list of the server that had it —
 * never neither. A take blocks, so an idle loop waits in Redis and is handed a
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
 * A take reads a single queue and holds its connection while it blocks, so the
 * server uses one Redis connection per method, plus one shared by response writes and the
 * heartbeat.
 */
public class AnyCallServerImpl implements AnyCallServer {

    private static final Logger log = LoggerFactory.getLogger(AnyCallServerImpl.class);
    // How long a method's read loop blocks on its queue before looking again. Bounds how
    // long stop() and unregister() take to reach an idle loop; an idle loop costs one
    // command per this period.
    private static final long TAKE_BLOCK_SECONDS = 2;

    private static final Duration HEARTBEAT_PERIOD = Duration.ofSeconds(2);
    private static final Duration HEARTBEAT_TTL = AnycallQueues.HEARTBEAT_TTL;
    // KEYS[1] = live servers sorted set, ARGV[1] = server id, ARGV[2] = ttl seconds,
    // ARGV[3] = '1' on the server id's first heartbeat. A server whose entry is gone, or
    // older than the ttl, was declared dead: past its first heartbeat, it gets {-1} and
    // nothing is written, so a dead server never comes back. Otherwise refreshes its entry
    // and returns {0, every member older than the ttl}. Prunes nothing: a dead server
    // leaves the set only once AnycallReaping has emptied its processing list, so that list
    // is never forgotten.
    // Kept byte-for-byte identical to the Python server's copy.
    private static final String HEARTBEAT_SCRIPT = """
        local t = redis.call('TIME')
        local now = tonumber(t[1]) + tonumber(t[2]) / 1000000
        local stale = string.format('%.6f', now - tonumber(ARGV[2]))
        if ARGV[3] ~= '1' then
          local score = redis.call('ZSCORE', KEYS[1], ARGV[1])
          if not score or tonumber(score) < tonumber(stale) then return {-1} end
        end
        redis.call('ZADD', KEYS[1], string.format('%.6f', now), ARGV[1])
        local result = redis.call('ZRANGEBYSCORE', KEYS[1], '-inf', '(' .. stale)
        table.insert(result, 1, 0)
        return result
        """;

    /**
     * The server id this server heartbeats and takes requests under. Replaced by a new one
     * when the server is declared dead, and the old one drains (see {@link #drain}): requests taken under it
     * one are failed back by reapers, so their results are discarded.
     */
    private final class Identity {
        final String serverId = UUID.randomUUID().toString();
        final String processingKey = queues.processingList(serverId);
        // Whether its first heartbeat went through: no request is taken under an id before.
        volatile boolean registered;
        // Takes started under this id and not returned yet, guarded by identityLock. Once it
        // drains and this reaches 0, nothing can land on its list anymore, and its tombstone
        // can go.
        int activeTakes;
    }

    private static final ObjectMapper OBJECT_MAPPER = new ObjectMapper();

    private final RedisClient redisClient;
    private final StatefulRedisConnection<String, String> writeConnection;
    private final RedisCommands<String, String> writeCommands;
    // The write connection's async view, so a tick can give up after one period.
    private final RedisAsyncCommands<String, String> heartbeatCommands;
    // For reaping, used only by the heartbeat: its WATCH and MULTI belong to the connection,
    // so they can't share the write connection with the workers' responses.
    private final StatefulRedisConnection<String, String> reapConnection;
    // Draining identities whose lists still need a last pass; only the heartbeat touches it.
    // Guards identity, draining and every identity's activeTakes: a read loop counts its take
    // under the same lock a drain switches ids under, so once an id drains, no new take can
    // start on it. Read loops also wait on it for a new id's first heartbeat.
    private final Object identityLock = new Object();
    // Ids that drained and whose tombstone still has to be deleted.
    private final List<Identity> draining = new ArrayList<>();
    // Wakes the heartbeat early, to register a new id right after a drain.
    private final Semaphore heartbeatWake = new Semaphore(0);
    // Whether to take with BLMOVE (Redis 6.2+) or BRPOPLPUSH, which 6.2 deprecates. Asked
    // of Redis on start (see detectBlmove).
    private volatile boolean useBlmove;

    private final Map<String, MethodHandler> methodHandlers;
    // Each method's cap, changed by setMaxConcurrency while requests run.
    private final Map<String, ConcurrencyLimit> methodConcurrencyLimiters;
    // Each method's requests being processed by a worker right now. Kept across a method
    // registered again, whose old requests may still be running.
    private final Map<String, AtomicInteger> runningRequests = new ConcurrentHashMap<>();
    private final Set<String> inFlightRequestIds;
    private final AtomicBoolean running;
    private final AtomicBoolean closed = new AtomicBoolean(false);
    private final AnycallQueues queues;
    // The server-wide cap; updateOptions may change it while requests run.
    private final ConcurrencyLimit globalConcurrencyLimiter;
    private volatile Identity identity;
    // Read loops and the heartbeat, apart from the workers so stop() can wait for every
    // loop to exit before the worker pool stops taking requests.
    private ExecutorService loops;
    private ExecutorService workers;

    /**
     * @param queues  the keys this server takes from and writes to
     * @param options its settings; a setting left out means no limit
     */
    public AnyCallServerImpl(String redisUri, AnycallQueues queues, ServerOptions options) {
        if (redisUri == null || redisUri.isEmpty()) {
            throw new IllegalArgumentException("AnyCall Server: redisUri must not be null or blank");
        }
        this.queues = queues == null ? AnycallQueues.DEFAULT : queues;
        this.identity = new Identity();
        this.globalConcurrencyLimiter = new ConcurrencyLimit(
            (options == null ? ServerOptions.DEFAULT : options).maxConcurrencyOr(null));
        this.redisClient = RedisClient.create(redisUri);
        // RESP2: Redis 5 has no HELLO, so no RESP3.
        this.redisClient.setOptions(ClientOptions.builder().protocolVersion(ProtocolVersion.RESP2).build());
        this.writeConnection = redisClient.connect();
        this.writeCommands = writeConnection.sync();
        this.heartbeatCommands = writeConnection.async();
        this.reapConnection = redisClient.connect();
        this.methodHandlers = new ConcurrentHashMap<>();
        this.methodConcurrencyLimiters = new ConcurrentHashMap<>();
        this.inFlightRequestIds = ConcurrentHashMap.newKeySet();
        this.running = new AtomicBoolean(false);
    }

    /**
     * Starts the server and begins processing incoming requests from Redis.
     * Spawns one read loop per registered method, the heartbeat, and the worker pool
     * that processes taken requests. This method is idempotent - repeated calls have no
     * effect if already running.
     *
     * @return this server instance for method chaining
     * @throws AnyCallError if the first heartbeat fails; the server is left stopped and can
     *                      be started again
     * @throws IllegalStateException if the server is closed
     */
    @Override
    public synchronized AnyCallServer start() {
        if (closed.get()) {
            throw new IllegalStateException("AnyCall Server: closed, can't be started again");
        }
        if (!running.get()) {
            // A restart starts clean: the last run's id ages out with an empty list.
            if (identity.registered) {
                identity = new Identity();
            }
            log.info("Starting AnyCall server {}", identity.serverId);
            try {
                useBlmove = detectBlmove();
            } catch (Exception e) {
                throw new AnyCallError("AnyCall Server", "Failed to ask Redis for BLMOVE, not starting: "
                    + e.getMessage(), e);
            }
            log.info("Taking requests with {}", useBlmove ? "BLMOVE" : "BRPOPLPUSH");
            // Heartbeat once before taking any request: a server missing from the live set
            // is never looked at by reaping, so a request it took would be lost if it then
            // crashed.
            try {
                heartbeat();
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
                throw new AnyCallError("AnyCall Server", "Interrupted while writing the first heartbeat", e);
            } catch (Exception e) {
                throw new AnyCallError("AnyCall Server",
                    "Failed to write the first heartbeat, not starting: " + describe(e), e);
            }
            running.set(true);
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

    @Override
    public ServerOptions options() {
        Integer cap = globalConcurrencyLimiter.capacity();
        return cap == null ? ServerOptions.DEFAULT.withNoConcurrencyLimit() : ServerOptions.DEFAULT.withMaxConcurrency(cap);
    }

    @Override
    public void updateOptions(ServerOptions options) {
        if (options == null) {
            return;
        }
        globalConcurrencyLimiter.setCapacity(options.maxConcurrencyOr(globalConcurrencyLimiter.capacity()));
    }

    @Override
    public synchronized List<String> methods() {
        return methodHandlers.keySet().stream().sorted().toList();
    }

    @Override
    public synchronized MethodInfo method(String name) {
        if (!methodHandlers.containsKey(name)) {
            throw new IllegalArgumentException("No method registered as '" + name + "'");
        }
        return new MethodInfo(methodConcurrencyLimiters.get(name).capacity(), runningRequests.get(name).get(),
            methodHandlers.get(name).declared());
    }

    @Override
    public synchronized void setMaxConcurrency(String method, int maxConcurrency) {
        if (maxConcurrency < 1) {
            throw new IllegalArgumentException("maxConcurrency must be at least 1; got " + maxConcurrency);
        }
        if (!methodHandlers.containsKey(method)) {
            throw new IllegalArgumentException("No method registered as '" + method + "'");
        }
        methodConcurrencyLimiters.get(method).setCapacity(maxConcurrency);
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

    @Override
    @SuppressWarnings("unchecked")
    public AnyCallServer register(SupplyMethod declared, SupplyHandler<?, ?> handler) {
        if (declared == null || declared.name() == null || declared.name().isBlank()) {
            throw new IllegalArgumentException("AnyCall Server: a method needs a name");
        }
        if (declared.maxConcurrency() < 1) {
            throw new IllegalArgumentException("AnyCall Server: " + declared.name() + " has maxConcurrency "
                + declared.maxConcurrency() + "; it must be at least 1");
        }
        if (declared.requestType() == null || handler == null) {
            throw new IllegalArgumentException("AnyCall Server: " + declared.name()
                + " needs a request type and a handler");
        }
        registerHandler(new MethodHandler(declared, (SupplyHandler<Object, Object>) handler));
        return this;
    }

    private void scanAndRegisterSupplier(Object supplier) {
        for (MethodHandler handler : SupplyScanner.scan(supplier)) {
            registerHandler(handler);
        }
    }

    private void registerHandler(MethodHandler handler) {
        String methodName = handler.methodName();
        synchronized (this) {
            methodConcurrencyLimiters.put(methodName, new ConcurrencyLimit(handler.maxConcurrency()));
            runningRequests.computeIfAbsent(methodName, name -> new AtomicInteger());
            // Replacing a handler makes the old one's loop exit on its next
            // iteration; the new one gets a loop of its own.
            methodHandlers.put(methodName, handler);
            if (running.get()) {
                startReader(methodName, handler);
            }
        }
        log.debug("Registered method: {} (maxConcurrency={})", methodName, handler.maxConcurrency());
    }

    /**
     * Stops the server. Read loops notice within {@link #TAKE_BLOCK_SECONDS}; the requests
     * already taken are run to completion and answered, however long that takes.
     * Interrupting the thread that called this gives up on them: they stay on the processing
     * list, to be failed back once this server stops heartbeating.
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
            loops.awaitTermination(Long.MAX_VALUE, TimeUnit.NANOSECONDS);
            workers.shutdown();
            workers.awaitTermination(Long.MAX_VALUE, TimeUnit.NANOSECONDS);
        } catch (InterruptedException e) {
            loops.shutdownNow();
            workers.shutdownNow();
            Thread.currentThread().interrupt();
        }
    }

    /**
     * Stops the server, then closes its connections and Redis client. If the stop was
     * interrupted, requests given up on may still be running; their responses then fail to
     * send, as the stop's interrupt already promised.
     */
    @Override
    public void close() {
        if (!closed.compareAndSet(false, true)) {
            return;
        }
        stop();
        // An interrupted stop leaves the flag set, which would make the shutdown below give up.
        boolean interrupted = Thread.interrupted();
        try {
            reapConnection.close();
            writeConnection.close();
            redisClient.shutdown();
        } finally {
            if (interrupted) {
                Thread.currentThread().interrupt();
            }
        }
        log.info("Closed AnyCall server");
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
     * This server's current id — the member it registers under in {@code anycall:servers:alive}.
     * A new one is generated on every start, and whenever the server is declared dead; an id
     * is never reused.
     *
     * @return this server's id
     */
    public String getServerId() {
        return identity.serverId;
    }

    /**
     * Keeps this server's entry in the heartbeat sorted set fresh, so clients
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
                heartbeatWake.tryAcquire(HEARTBEAT_PERIOD.toMillis(), TimeUnit.MILLISECONDS);
                heartbeatWake.drainPermits();
                if (running.get()) {
                    heartbeatTick();
                }
            }
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
        }
    }

    /**
     * Whether Redis has {@code BLMOVE}, asked with {@code COMMAND INFO BLMOVE}, which answers
     * nil for a command Redis doesn't have. Asks for the command rather than reading the
     * version, which servers compatible with Redis don't always report faithfully.
     */
    private boolean detectBlmove() {
        List<Object> info = writeCommands.commandInfo("BLMOVE");
        return info != null && !info.isEmpty() && info.get(0) != null;
    }

    /**
     * A heartbeat of the running server: a failure only logs, and the next tick tries again.
     */
    private void heartbeatTick() {
        try {
            heartbeat();
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
        } catch (Exception e) {
            log.warn("Failed to write heartbeat: {}", describe(e));
        }
    }

    private static String describe(Exception e) {
        if (e instanceof TimeoutException) {
            return "timed out after " + HEARTBEAT_PERIOD.toMillis() + "ms";
        }
        if (e instanceof ExecutionException && e.getCause() != null) {
            return e.getCause().getMessage();
        }
        return e.getMessage();
    }

    /**
     * One heartbeat, as a single {@code EVAL} of {@link #HEARTBEAT_SCRIPT}: refresh this
     * server's entry under Redis's own clock ({@code TIME}) and read back the servers whose
     * heartbeat is older than {@link #HEARTBEAT_TTL}, then fail back whatever those were still
     * processing. If this server was declared dead meanwhile, its id drains and it heartbeats
     * under a new one instead (see {@link #drain}).
     * <p>
     * "Now" is Redis's clock, not this host's, so scores written and compared by different
     * servers are always on the same clock — skew between hosts can't make a live server
     * look dead or a dead one alive. Throws if the heartbeat itself fails or takes longer
     * than {@link #HEARTBEAT_PERIOD}; reaping failures only log.
     */
    private void heartbeat() throws Exception {
        Identity current = identity;
        RedisFuture<List<Object>> future = heartbeatCommands.eval(HEARTBEAT_SCRIPT, ScriptOutputType.MULTI,
            new String[] {queues.heartbeatKey()}, current.serverId, String.valueOf(HEARTBEAT_TTL.getSeconds()),
            current.registered ? "0" : "1");
        List<Object> result = future.get(HEARTBEAT_PERIOD.toMillis(), TimeUnit.MILLISECONDS);

        if (Long.valueOf(-1).equals(result.get(0))) {
            drain(current);
            heartbeat();
            return;
        }
        current.registered = true;
        synchronized (identityLock) {
            identityLock.notifyAll();  // read loops waiting for this id can take now
        }

        List<String> dead = new ArrayList<>(result.size() - 1);
        for (Object member : result.subList(1, result.size())) {
            dead.add((String) member);
        }
        RedisCommands<String, String> reap = reapConnection.sync();
        AnycallReaping.reapDeadServers(reap, queues, dead);

        // A draining id with no take left on it can't get anything on its list anymore: make
        // sure its list was reaped, then delete its tombstone.
        List<Identity> idle = new ArrayList<>();
        synchronized (identityLock) {
            for (Identity old : draining) {
                if (old.activeTakes == 0) {
                    idle.add(old);
                }
            }
            draining.removeAll(idle);
        }
        for (Identity old : idle) {
            AnycallReaping.reapDeadServers(reap, queues, List.of(old.serverId));
            AnycallReaping.dropTombstone(reap, queues, old.serverId);
        }
    }

    /**
     * Drains an id this server was declared dead under, which never heartbeats again, and
     * carries on under a new one. The requests taken under the draining id are failed back
     * by reapers, so the ones still running here finish with their results discarded, holding
     * their concurrency slots until then.
     * <p>
     * Called by the heartbeat when Redis refuses it, or by a read loop whose take hit the
     * id's tombstone; whichever comes first drains, the other finds the id already switched.
     * Read loops wait until the new id's first heartbeat, which this wakes at once.
     */
    private void drain(Identity old) {
        Identity fresh;
        synchronized (identityLock) {
            if (identity != old) {
                return;  // already drained, by the heartbeat or another read loop
            }
            fresh = new Identity();
            identity = fresh;
            draining.add(old);
        }
        heartbeatWake.release();
        log.warn("Server {} was declared dead (no heartbeat for over {}s): draining it and "
            + "continuing as {}; the requests it had taken are failed back to their clients, "
            + "and their results discarded", old.serverId, HEARTBEAT_TTL.getSeconds(), fresh.serverId);
    }

    /**
     * Read loop for one method's queue, until the server stops or the method is
     * unregistered (or registered again, which starts a new loop). Waits for a free
     * permit of the method before every take, so it never takes a request it has no room
     * to run. Holds a connection of its own, since a take blocks it.
     */
    private void readMethod(String methodName, MethodHandler handler) {
        String queueKey = queues.requestQueue(methodName);
        ConcurrencyLimit methodLimiter = methodConcurrencyLimiters.get(methodName);
        log.info("Started reading queue {}", queueKey);

        while (isCurrent(methodName, handler)) {
            try (StatefulRedisConnection<String, String> connection = redisClient.connect()) {
                RedisCommands<String, String> commands = connection.sync();
                while (isCurrent(methodName, handler)) {
                    if (!methodLimiter.tryAcquire(TimeUnit.SECONDS.toMillis(TAKE_BLOCK_SECONDS))) {
                        continue;
                    }
                    Identity taker;
                    synchronized (identityLock) {
                        taker = identity;
                        if (taker.registered) {
                            taker.activeTakes++;
                        }
                    }
                    if (!taker.registered) {
                        // Just drained: wait for the new id's first heartbeat.
                        methodLimiter.release();
                        synchronized (identityLock) {
                            if (!identity.registered) {
                                identityLock.wait(TimeUnit.SECONDS.toMillis(TAKE_BLOCK_SECONDS));
                            }
                        }
                        continue;
                    }
                    String item;
                    try {
                        item = useBlmove
                            ? commands.blmove(queueKey, taker.processingKey, LMoveArgs.Builder.rightLeft(), TAKE_BLOCK_SECONDS)
                            : commands.brpoplpush(TAKE_BLOCK_SECONDS, queueKey, taker.processingKey);
                    } catch (RedisCommandExecutionException e) {
                        methodLimiter.release();
                        if (e.getMessage() != null && e.getMessage().startsWith("WRONGTYPE")) {
                            // Our list is a tombstone: this id was reaped, so it's dead. The
                            // request stays in its queue.
                            drain(taker);
                            continue;
                        }
                        throw e;
                    } catch (RuntimeException e) {
                        methodLimiter.release();
                        throw e;
                    } finally {
                        synchronized (identityLock) {
                            taker.activeTakes--;
                        }
                    }
                    if (item == null) {
                        methodLimiter.release();
                        continue;
                    }
                    dispatch(methodName, item, handler, methodLimiter, taker);
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
    private void dispatch(String methodName, String item, MethodHandler handler, ConcurrencyLimit methodLimiter,
                          Identity taker)
            throws InterruptedException {
        try {
            globalConcurrencyLimiter.acquire();
        } catch (InterruptedException e) {
            methodLimiter.release();
            throw e;
        }
        AtomicInteger runningNow = runningRequests.get(methodName);
        workers.submit(() -> {
            runningNow.incrementAndGet();
            try {
                processRequest(item, handler, taker);
            } finally {
                runningNow.decrementAndGet();
                globalConcurrencyLimiter.release();
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
     * @param taker the identity it was taken under; if draining by the time it's done, its
     *              result is discarded
     */
    private void processRequest(String requestJson, MethodHandler handler, Identity taker) {
        String requestId = null;
        String clientId = null;
        String methodName = null;

        try {
            AnyCallRequest request = OBJECT_MAPPER.readValue(requestJson, AnyCallRequest.class);
            // Jackson fills a missing field with null instead of failing.
            if (request.requestId() == null || request.clientId() == null || request.methodName() == null
                    || request.payload() == null) {
                throw new IllegalArgumentException("Request is missing a field: " + requestJson);
            }
            requestId = request.requestId();
            clientId = request.clientId();
            methodName = request.methodName();
            inFlightRequestIds.add(requestId);

            log.debug("Processing request: {} for method: {}", requestId, methodName);

            Object parameter = OBJECT_MAPPER.readValue(request.payload(), handler.parameterType());

            AnycallContext ctx = new AnycallContext(requestId, methodName);
            Object result = handler.handler().handle(ctx, parameter);

            String resultJson = OBJECT_MAPPER.writeValueAsString(result);

            AnyCallResponse response = AnyCallResponse.success(requestId, resultJson);
            sendResponse(response, clientId, requestJson, taker);

            log.debug("Request {} processed successfully", requestId);
        } catch (Exception e) {
            if (requestId == null || clientId == null) {
                AnyCallRequest.ReplyAddress address = AnyCallRequest.readReplyAddress(requestJson);
                if (address == null) {
                    log.warn("Dropped a request with no readable requestId or clientId: {}", e.getMessage());
                    release(requestJson, taker);
                    return;
                }
                requestId = address.requestId();
                clientId = address.clientId();
            }
            log.error("Error processing request: {}", requestId, e);
            AnyCallResponse response = AnyCallResponse.error(
                requestId,
                e.getMessage() != null ? e.getMessage() : e.getClass().getName()
            );
            sendResponse(response, clientId, requestJson, taker);
        } finally {
            if (requestId != null) {
                inFlightRequestIds.remove(requestId);
            }
        }
    }

    /**
     * Drops a request from this server's processing list without answering it, for one with
     * no response queue to answer on.
     *
     * @param requestJson the request json exactly as it was taken
     * @param taker the identity it was taken under
     */
    private void release(String requestJson, Identity taker) {
        if (taker != identity) {
            return;  // a draining identity's list belongs to the reapers now
        }
        try {
            writeCommands.lrem(taker.processingKey, 1, requestJson);
        } catch (Exception e) {
            log.error("Error dropping a request from the processing list", e);
        }
    }

    /**
     * Sends a response back to the client and drops its request from this server's
     * processing list, in one script: the push runs first, so if it never happens the
     * request is still on the list to be failed back.
     *
     * @param response the response to send
     * @param clientId the client that made the call, whose queue the response goes to
     * @param requestJson the request json exactly as it was taken
     * @param taker the identity it was taken under; a draining one's result is discarded,
     *              since reapers fail its requests back
     */
    private void sendResponse(AnyCallResponse response, String clientId, String requestJson, Identity taker) {
        if (taker != identity) {
            log.debug("Discarded the result of request {}, taken under draining id {}",
                response.requestId(), taker.serverId);
            return;
        }
        try {
            AnycallResponses.pushAndRelease(writeCommands, queues, response, clientId, taker.processingKey, requestJson);
        } catch (Exception e) {
            log.error("Error sending response: {}", response.requestId(), e);
        }
    }
}
