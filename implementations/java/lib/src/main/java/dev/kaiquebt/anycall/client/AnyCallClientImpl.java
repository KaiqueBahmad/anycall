package dev.kaiquebt.anycall.client;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import dev.kaiquebt.anycall.core.AnyCallClient;
import dev.kaiquebt.anycall.core.AsyncCalls;
import dev.kaiquebt.anycall.exception.*;
import dev.kaiquebt.anycall.model.AnyCallRequest;
import dev.kaiquebt.anycall.model.AnyCallResponse;
import dev.kaiquebt.anycall.publisher.AnycallQueues;
import dev.kaiquebt.anycall.publisher.AnycallReaping;
import dev.kaiquebt.anycall.registry.TypeRegistry;
import io.lettuce.core.ClientOptions;
import io.lettuce.core.KeyValue;
import io.lettuce.core.Range;
import io.lettuce.core.RedisClient;
import io.lettuce.core.RedisException;
import io.lettuce.core.api.StatefulRedisConnection;
import io.lettuce.core.api.sync.RedisCommands;
import io.lettuce.core.protocol.ProtocolVersion;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.time.Duration;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.CompletionException;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.TimeUnit;

/**
 * Internal implementation of AnyCallClient.
 * <p>
 * <strong>This class is not intended for direct use. Use {@link dev.kaiquebt.anycall.core.AnyCall#client(String)} instead.</strong>
 * </p>
 * Every response to this client's calls goes to one queue of its own,
 * {@code anycall:responses:<client id>}. A single reader thread blocks on it and hands each
 * response to the call waiting for it, by its request id, so any number of calls can wait at
 * once without a connection each: a blocking call waits on its future, an async one (see
 * {@link #async()}) returns it.
 */
public class AnyCallClientImpl implements AnyCallClient {

    private static final Logger log = LoggerFactory.getLogger(AnyCallClientImpl.class);
    // Zero means a call waits for its response with no limit.
    private static final Duration DEFAULT_TIMEOUT = Duration.ZERO;
    // Added on top of a read slice to get the connections' command timeout: no command
    // blocks longer than a slice, so one that outlasts this is stuck on a Redis that
    // stopped answering, and fails as a BrokerError.
    private static final Duration COMMAND_TIMEOUT_MARGIN = Duration.ofSeconds(5);
    // The reader blocks on the response queue in slices of at most this long; after each one
    // that ends empty while calls are waiting, it reaps dead servers itself (see
    // AnycallReaping), so their requests are failed back even with no server left alive to
    // do it.
    private static final Duration WAITER_REAP_SLICE = Duration.ofSeconds(10);
    private static final ObjectMapper OBJECT_MAPPER = new ObjectMapper();

    /** A call waiting for its response, until the reader hands it over. */
    private record Pending(String methodName, CompletableFuture<String> future) {
    }

    private final RedisClient redisClient;
    // For the calls' own commands (liveness, depth, publishing), none of which blocks: every
    // call shares it.
    private final StatefulRedisConnection<String, String> connection;
    private final RedisCommands<String, String> commands;
    private final Duration timeout;
    private final TypeRegistry registry;
    private volatile Long defaultMaxQueueDepth;
    private final String clientId = UUID.randomUUID().toString();
    private final String responseQueue = AnycallQueues.responseQueue(clientId);
    private final Map<String, Pending> pending = new ConcurrentHashMap<>();
    private final AsyncCalls asyncCalls = new AsyncView();
    private Thread reader;
    private volatile boolean closed;

    public AnyCallClientImpl(String redisUri, Duration timeout) {
        this(redisUri, timeout, null);
    }

    public AnyCallClientImpl(String redisUri, Duration timeout, Long defaultMaxQueueDepth) {
        if (redisUri == null || redisUri.isEmpty()) {
            throw new IllegalArgumentException("AnyCall Client: redisUri must not be null or blank");
        }
        this.timeout = timeout == null ? DEFAULT_TIMEOUT : timeout;
        this.registry = new TypeRegistry();
        this.defaultMaxQueueDepth = defaultMaxQueueDepth;

        this.redisClient = RedisClient.create(redisUri);
        // While disconnected, fail commands at once instead of queueing them for after a
        // reconnect: a Redis failure is surfaced as a BrokerError instead.
        // RESP2: Redis 5 has no HELLO, so no RESP3.
        this.redisClient.setOptions(ClientOptions.builder()
            .disconnectedBehavior(ClientOptions.DisconnectedBehavior.REJECT_COMMANDS)
            .protocolVersion(ProtocolVersion.RESP2)
            .build());
        this.connection = redisClient.connect();
        this.connection.setTimeout(WAITER_REAP_SLICE.plus(COMMAND_TIMEOUT_MARGIN));
        this.commands = connection.sync();
    }

    /** This client's id: its response queue is {@code anycall:responses:<id>}. */
    public String getClientId() {
        return clientId;
    }

    @Override
    public AsyncCalls async() {
        return asyncCalls;
    }

    /**
     * Makes a synchronous remote procedure call via Redis: publishes the request, waits for
     * its response, and deserializes the result.
     *
     * @param <T> the type of the expected response
     * @param methodName the name of the remote method to invoke
     * @param request the request payload object to be serialized
     * @param responseType the class type for deserializing the response
     * @return the deserialized response from the remote method
     * @throws AnyCallError if the call fails, times out, or the remote method returns an error
     */
    @Override
    public <T> T call(String methodName, Object request, Class<T> responseType) {
        return join(callAsync(methodName, request, responseType, defaultMaxQueueDepth));
    }

    @Override
    public <T> T call(String methodName, Object request, Class<T> responseType, long maxQueueDepth) {
        return join(callAsync(methodName, request, responseType, maxQueueDepth));
    }

    @Override
    public <T> T call(String methodName, Object request) {
        return join(callAsync(methodName, request, this.<T>registeredType(methodName), defaultMaxQueueDepth));
    }

    @Override
    public <T> T call(String methodName, Object request, long maxQueueDepth) {
        return join(callAsync(methodName, request, this.<T>registeredType(methodName), maxQueueDepth));
    }

    @Override
    public Map<String, Object> rawCall(String methodName, Object request) {
        return join(rawCallAsync(methodName, request, defaultMaxQueueDepth));
    }

    @Override
    public Map<String, Object> rawCall(String methodName, Object request, long maxQueueDepth) {
        return join(rawCallAsync(methodName, request, maxQueueDepth));
    }

    @Override
    public long getQueueDepth(String methodName) {
        return commands.llen(AnycallQueues.REQUEST_QUEUE_PREFIX + methodName);
    }

    @Override
    public void setDefaultMaxQueueDepth(Long maxQueueDepth) {
        this.defaultMaxQueueDepth = maxQueueDepth;
    }

    @Override
    public Long getDefaultMaxQueueDepth() {
        return defaultMaxQueueDepth;
    }

    @Override
    public void registerType(String operation, Class<?> responseType) {
        registry.register(operation, responseType);
    }

    /**
     * Stops reading responses. Calls still waiting fail when their timeout is up (or never,
     * with no timeout); make no calls after.
     */
    public void close() {
        closed = true;
    }

    @SuppressWarnings("unchecked")
    private <T> Class<T> registeredType(String methodName) {
        Class<?> resolved = registry.get(methodName);
        if (resolved == null) {
            throw new AnyCallError(
                "No response type registered for operation '" + methodName + "'. "
                    + "Either call with explicit type: call(\"" + methodName + "\", req, YourType), "
                    + "or register the type first: registerType(\"" + methodName + "\", YourType)."
            );
        }
        return (Class<T>) resolved;
    }

    @SuppressWarnings("unchecked")
    private CompletableFuture<Map<String, Object>> rawCallAsync(String methodName, Object request, Long maxQueueDepth) {
        return callAsync(methodName, request, (Class<Map<String, Object>>) (Class<?>) Map.class, maxQueueDepth);
    }

    /**
     * Publishes a call and returns the future of its result. An error at any point,
     * publishing included, completes the future exceptionally instead of being thrown.
     */
    private <T> CompletableFuture<T> callAsync(String methodName, Object request, Class<T> responseType,
                                                Long maxQueueDepth) {
        String requestId;
        CompletableFuture<String> response;
        try {
            AnyCallRequest anyCallRequest = AnyCallRequest.create(methodName, serialize(methodName, request), clientId);
            requestId = anyCallRequest.requestId();
            response = publish(methodName, anyCallRequest, maxQueueDepth);
        } catch (AnyCallError e) {
            return CompletableFuture.failedFuture(e);
        }
        if (!timeout.isZero()) {
            response.orTimeout(timeout.toMillis(), TimeUnit.MILLISECONDS);
        }
        return response.handle((responseJson, error) -> {
            pending.remove(requestId);
            if (error != null) {
                Throwable cause = error instanceof CompletionException && error.getCause() != null
                    ? error.getCause() : error;
                if (cause instanceof java.util.concurrent.TimeoutException) {
                    throw new TimeoutError(methodName, "Timeout waiting for response from method: " + methodName,
                        requestId);
                }
                if (cause instanceof AnyCallError anyCallError) {
                    throw anyCallError;
                }
                throw new AnyCallError(methodName, "Failed to call method: " + methodName, cause);
            }
            return outcome(methodName, requestId, responseJson, responseType);
        });
    }

    private static String serialize(String methodName, Object request) {
        try {
            return OBJECT_MAPPER.writeValueAsString(request);
        } catch (JsonProcessingException e) {
            throw new SerializationError(methodName, "Failed to serialize request for method: " + methodName, e);
        }
    }

    /**
     * Checks, then publishes a call, and returns the future its response will complete. The
     * future is in place before the {@code LPUSH}, so the response can't arrive before
     * anyone waits for it.
     */
    private CompletableFuture<String> publish(String methodName, AnyCallRequest request, Long maxQueueDepth) {
        String requestQueue = AnycallQueues.REQUEST_QUEUE_PREFIX + methodName;
        try {
            checkServerAvailable(methodName);
            if (maxQueueDepth != null) {
                long queueDepth = commands.llen(requestQueue);
                if (queueDepth >= maxQueueDepth) {
                    throw new QueueFullError(methodName, queueDepth, maxQueueDepth);
                }
            }
        } catch (RedisException e) {
            throw new BrokerError(methodName, "Redis failed before the request was published: " + e.getMessage(),
                request.requestId(), false, e);
        }

        String requestJson;
        try {
            requestJson = OBJECT_MAPPER.writeValueAsString(request);
        } catch (JsonProcessingException e) {
            throw new SerializationError(methodName, "Failed to serialize request for method: " + methodName, e);
        }

        CompletableFuture<String> response = new CompletableFuture<>();
        pending.put(request.requestId(), new Pending(methodName, response));
        startReader();
        try {
            commands.lpush(requestQueue, requestJson);
        } catch (RedisException e) {
            pending.remove(request.requestId());
            // The LPUSH may have reached Redis before the connection dropped.
            throw new BrokerError(methodName, "Redis failed after the request may have been published: "
                + e.getMessage(), request.requestId(), true, e);
        }
        return response;
    }

    /** Turns the response the reader handed over into the call's result, or its error. */
    private static <T> T outcome(String methodName, String requestId, String responseJson, Class<T> responseType) {
        AnyCallResponse response;
        try {
            response = OBJECT_MAPPER.readValue(responseJson, AnyCallResponse.class);
        } catch (JsonProcessingException e) {
            throw new SerializationError(methodName, "Invalid response from method: " + methodName, e);
        }
        if (response.lostServer() != null) {
            throw new ServerLostError(methodName, response.error(), requestId, response.lostServer());
        }
        if (response.hasError()) {
            throw new RemoteException(methodName, response.error(), "RemoteExecutionError");
        }
        // A method that returned null sends the payload "null"; a null payload without an
        // error is a broken response, not a null result.
        if (response.payload() == null) {
            throw new SerializationError(methodName, "Response from method " + methodName
                + " has neither a payload nor an error; the method may have run");
        }
        try {
            return OBJECT_MAPPER.readValue(response.payload(), responseType);
        } catch (JsonProcessingException e) {
            throw new SerializationError(methodName, "Failed to deserialize the result of method: " + methodName, e);
        }
    }

    /** Waits for an async call, throwing its own error instead of a wrapped one. */
    private static <T> T join(CompletableFuture<T> future) {
        try {
            return future.get();
        } catch (ExecutionException e) {
            if (e.getCause() instanceof RuntimeException runtime) {
                throw runtime;
            }
            throw new AnyCallError("Call failed", e.getCause());
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            throw new AnyCallError("Interrupted while waiting for a call", e);
        }
    }

    /**
     * Fails fast, before publishing, if no server has heartbeated recently enough to be
     * considered alive. Mirrors a connection-refused error over plain HTTP: without this,
     * a request would be queued and the caller would silently wait out the full timeout
     * with no server around to ever pop it.
     *
     * @throws NoServerAvailableError if no server is alive
     */
    private void checkServerAvailable(String methodName) {
        Long aliveCount = commands.zcount(AnycallQueues.HEARTBEAT_KEY, aliveRange(commands));
        if (aliveCount == null || aliveCount == 0) {
            throw new NoServerAvailableError(methodName);
        }
    }

    /**
     * Heartbeat scores still within {@link AnycallQueues#HEARTBEAT_TTL} of Redis's own
     * clock ({@code TIME}), so skew between hosts can't make a live server look dead.
     */
    private static Range<Double> aliveRange(RedisCommands<String, String> commands) {
        List<String> time = commands.time();
        double now = Double.parseDouble(time.get(0)) + Double.parseDouble(time.get(1)) / 1_000_000.0;
        double since = now - AnycallQueues.HEARTBEAT_TTL.getSeconds();
        return Range.create(since, Double.POSITIVE_INFINITY);
    }

    /** Starts the reader on the first call. */
    private synchronized void startReader() {
        if (reader == null) {
            reader = new Thread(this::readResponses, "anycall-responses");
            reader.setDaemon(true);
            reader.start();
        }
    }

    /**
     * Reads this client's response queue and hands each response to the call waiting for it,
     * by its request id, until the client closes.
     * <p>
     * Reads in slices of {@link #WAITER_REAP_SLICE}; after each one that ends empty with calls
     * still waiting, reaps dead servers (see {@link #reap}). It holds two connections of its
     * own: one blocked in {@code BRPOP}, and one for reaping, whose {@code WATCH} and
     * {@code MULTI} belong to it. If Redis fails, every waiting call fails with a
     * {@link BrokerError}, and reading starts over.
     */
    private void readResponses() {
        StatefulRedisConnection<String, String> readConnection = null;
        StatefulRedisConnection<String, String> reapConnection = null;
        while (!closed) {
            try {
                if (readConnection == null) {
                    readConnection = redisClient.connect();
                    readConnection.setTimeout(WAITER_REAP_SLICE.plus(COMMAND_TIMEOUT_MARGIN));
                    reapConnection = redisClient.connect();
                }
                KeyValue<String, String> entry = readConnection.sync().brpop(WAITER_REAP_SLICE.getSeconds(), responseQueue);
                if (entry != null) {
                    handOver(entry.getValue());
                } else if (!pending.isEmpty()) {
                    reap(reapConnection.sync());
                }
            } catch (RedisException e) {
                failAll(e);
                try {
                    Thread.sleep(1000);
                } catch (InterruptedException interrupted) {
                    Thread.currentThread().interrupt();
                    return;
                }
            }
        }
    }

    private void handOver(String responseJson) {
        String requestId = AnyCallRequest.readField(responseJson, "requestId");
        Pending call = requestId == null ? null : pending.remove(requestId);
        if (call == null) {
            // A late answer to a call that timed out, or one with no readable request id:
            // there's no call to hand it to.
            log.debug("Dropped a response no call is waiting for: request {}", requestId);
            return;
        }
        call.future().complete(responseJson);
    }

    /** Fails every waiting call after Redis failed under the reader. */
    private void failAll(RedisException error) {
        for (String requestId : pending.keySet()) {
            Pending call = pending.remove(requestId);
            if (call != null) {
                call.future().completeExceptionally(new BrokerError(call.methodName(),
                    "Redis failed after the request may have been published: " + error.getMessage(),
                    requestId, true, error));
            }
        }
    }

    /**
     * Fails back the requests of every server that stopped heartbeating: the same work a
     * server does on its heartbeat, one script call when no server is dead. Failures only
     * log; the reader goes back to reading either way.
     */
    private static void reap(RedisCommands<String, String> reap) {
        try {
            AnycallReaping.reapDeadServers(reap, AnycallReaping.staleServers(reap));
        } catch (Exception e) {
            log.warn("Failed to reap dead servers: {}", e.getMessage());
        }
    }

    /** {@link #async()}: the same calls, returning their futures. */
    private final class AsyncView implements AsyncCalls {

        @Override
        public <T> CompletableFuture<T> call(String methodName, Object request, Class<T> responseType) {
            return callAsync(methodName, request, responseType, defaultMaxQueueDepth);
        }

        @Override
        public <T> CompletableFuture<T> call(String methodName, Object request, Class<T> responseType,
                                             long maxQueueDepth) {
            return callAsync(methodName, request, responseType, maxQueueDepth);
        }

        @Override
        public <T> CompletableFuture<T> call(String methodName, Object request) {
            Class<T> type;
            try {
                type = registeredType(methodName);
            } catch (AnyCallError e) {
                return CompletableFuture.failedFuture(e);
            }
            return callAsync(methodName, request, type, defaultMaxQueueDepth);
        }

        @Override
        public <T> CompletableFuture<T> call(String methodName, Object request, long maxQueueDepth) {
            Class<T> type;
            try {
                type = registeredType(methodName);
            } catch (AnyCallError e) {
                return CompletableFuture.failedFuture(e);
            }
            return callAsync(methodName, request, type, maxQueueDepth);
        }

        @Override
        public CompletableFuture<Map<String, Object>> rawCall(String methodName, Object request) {
            return rawCallAsync(methodName, request, defaultMaxQueueDepth);
        }

        @Override
        public CompletableFuture<Map<String, Object>> rawCall(String methodName, Object request, long maxQueueDepth) {
            return rawCallAsync(methodName, request, maxQueueDepth);
        }
    }
}
