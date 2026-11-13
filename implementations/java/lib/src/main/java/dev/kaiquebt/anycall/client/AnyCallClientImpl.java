package dev.kaiquebt.anycall.client;

import com.fasterxml.jackson.databind.ObjectMapper;
import dev.kaiquebt.anycall.core.AnyCallClient;
import dev.kaiquebt.anycall.exception.*;
import dev.kaiquebt.anycall.model.AnyCallRequest;
import dev.kaiquebt.anycall.model.AnyCallResponse;
import dev.kaiquebt.anycall.publisher.AnycallQueues;
import dev.kaiquebt.anycall.publisher.AnycallReaping;
import dev.kaiquebt.anycall.registry.TypeRegistry;
import io.lettuce.core.ClientOptions;
import io.lettuce.core.KeyValue;
import io.lettuce.core.protocol.ProtocolVersion;
import io.lettuce.core.Range;
import io.lettuce.core.RedisClient;
import io.lettuce.core.RedisException;
import io.lettuce.core.api.StatefulRedisConnection;
import io.lettuce.core.api.sync.RedisCommands;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.time.Duration;
import java.util.List;
import java.util.Map;

/**
 * Internal implementation of AnyCallClient.
 * <p>
 * <strong>This class is not intended for direct use. Use {@link dev.kaiquebt.anycall.core.AnyCall#client(String)} instead.</strong>
 * </p>
 */
public class AnyCallClientImpl implements AnyCallClient {

    private static final Logger log = LoggerFactory.getLogger(AnyCallClientImpl.class);
    // Zero means a call waits for its response with no limit.
    private static final Duration DEFAULT_TIMEOUT = Duration.ZERO;
    // Added on top of a wait slice to get the connection's command timeout: no command
    // blocks longer than a slice, so one that outlasts this is stuck on a Redis that
    // stopped answering, and fails as a BrokerError.
    private static final Duration COMMAND_TIMEOUT_MARGIN = Duration.ofSeconds(5);
    // A call waits for its response in slices of at most this long; after each one that
    // ends empty, it reaps dead servers itself (see AnycallReaping), so its request is
    // failed back even with no server left alive to do it.
    private static final Duration WAITER_REAP_SLICE = Duration.ofSeconds(10);
    private static final ObjectMapper OBJECT_MAPPER = new ObjectMapper();

    private final RedisClient redisClient;
    private final StatefulRedisConnection<String, String> connection;
    private final RedisCommands<String, String> commands;
    private final Duration timeout;
    private final TypeRegistry registry;
    private volatile Long defaultMaxQueueDepth;
    // For reaping, opened the first time a wait slice ends empty. Separate from
    // `connection`, which may be blocked in another thread's BRPOP; never blocks itself, so
    // every call can share it.
    private volatile StatefulRedisConnection<String, String> reapConnection;

    public AnyCallClientImpl(String redisUri, Duration timeout) {
        this(redisUri, timeout, null);
    }

    public AnyCallClientImpl(String redisUri, Duration timeout, Long defaultMaxQueueDepth) {
        if (redisUri == null || redisUri.isEmpty()) {
            throw new IllegalArgumentException("AnyCall Client: redisUri must not be null or blank");
        }
        if (timeout == null) {
            this.timeout = DEFAULT_TIMEOUT;
        } else {
            this.timeout = timeout;
        }
        this.registry = new TypeRegistry();
        this.defaultMaxQueueDepth = defaultMaxQueueDepth;

        this.redisClient = RedisClient.create(redisUri);
        // While disconnected, fail commands at once instead of queueing them for after a
        // reconnect: a call blocked on a dead Redis would otherwise wait forever with no
        // timeout, and a Redis failure is surfaced as a BrokerError instead.
        // RESP2: Redis 5 has no HELLO, so no RESP3.
        this.redisClient.setOptions(ClientOptions.builder()
            .disconnectedBehavior(ClientOptions.DisconnectedBehavior.REJECT_COMMANDS)
            .protocolVersion(ProtocolVersion.RESP2)
            .build());
        this.connection = redisClient.connect();
        // Every BRPOP lasts a slice at most, whatever the call's timeout: a call with no limit
        // still never blocks a command on a dead Redis forever.
        this.connection.setTimeout(WAITER_REAP_SLICE.plus(COMMAND_TIMEOUT_MARGIN));
        this.commands = connection.sync();
    }

    /**
     * Makes a synchronous remote procedure call via Redis.
     * Serializes the request, publishes it to the appropriate request queue,
     * waits for the response on a dedicated queue, and deserializes the result.
     *
     * @param <T> the type of the expected response
     * @param methodName the name of the remote method to invoke
     * @param request the request payload object to be serialized
     * @param responseType the class type for deserializing the response
     * @return the deserialized response from the remote method
     * @throws dev.kaiquebt.anycall.exception.AnyCallException if the call fails, times out,
     *         or the remote method returns an error
     */
	@Override
    public <T> T call(String methodName, Object request, Class<T> responseType) {
        return call(methodName, request, responseType, defaultMaxQueueDepth);
    }

    @Override
    public <T> T call(String methodName, Object request, Class<T> responseType, long maxQueueDepth) {
        return call(methodName, request, responseType, (Long) maxQueueDepth);
    }

    private <T> T call(String methodName, Object request, Class<T> responseType, Long maxQueueDepth) {
        String responseQueue = null;
        String requestId = null;
        // Set just before the LPUSH: from then on the request may have reached Redis.
        boolean published = false;
        boolean redisFailed = false;

        try {
            String requestQueue = AnycallQueues.REQUEST_QUEUE_PREFIX + methodName;

            String payload = OBJECT_MAPPER.writeValueAsString(request);
            AnyCallRequest anyCallRequest = AnyCallRequest.create(methodName, payload);
            requestId = anyCallRequest.requestId();
            String requestJson = OBJECT_MAPPER.writeValueAsString(anyCallRequest);

            checkServerAvailable(methodName);

            if (maxQueueDepth != null) {
                long queueDepth = commands.llen(requestQueue);
                if (queueDepth >= maxQueueDepth) {
                    throw new QueueFullError(methodName, queueDepth, maxQueueDepth);
                }
            }

            published = true;
            commands.lpush(requestQueue, requestJson);

            responseQueue = AnycallQueues.RESPONSE_QUEUE_PREFIX + requestId;
            String responseJson = readResponse(responseQueue);

            if (responseJson == null) {
                throw new TimeoutError(
                    methodName,
                    "Timeout waiting for response from method: " + methodName,
                    requestId
                );
            }

            AnyCallResponse response = OBJECT_MAPPER.readValue(responseJson, AnyCallResponse.class);

            if (response.lostServer() != null) {
                throw new ServerLostError(methodName, response.error(), requestId, response.lostServer());
            }
            if (response.hasError()) {
                throw new RemoteException(methodName, response.error(), "RemoteExecutionError");
            }
            // A method that returned null sends the payload "null"; a null payload without
            // an error is a broken response, not a null result.
            if (response.payload() == null) {
                throw new SerializationError(methodName, "Response from method " + methodName
                    + " has neither a payload nor an error; the method may have run");
            }

            return OBJECT_MAPPER.readValue(response.payload(), responseType);
        } catch (Exception e) {
            if (e instanceof AnyCallError) {
                throw (AnyCallError) e;
            }
            if (e instanceof RedisException) {
                redisFailed = true;
                throw new BrokerError(methodName, published
                    ? "Redis failed after the request may have been published: " + e.getMessage()
                    : "Redis failed before the request was published: " + e.getMessage(),
                    requestId, published, e);
            }
            if (e instanceof com.fasterxml.jackson.core.JsonProcessingException) {
                throw new SerializationError(methodName, "Failed to serialize/deserialize method call: " + methodName, e);
            }
            throw new AnyCallError(methodName, "Failed to call method: " + methodName, e);
        } finally {
            // After a Redis failure the DEL would only wait out the command timeout again.
            // Nothing is lost: a response queue only exists once a response is written,
            // and every write sets its RESPONSE_TTL.
            if (responseQueue != null && !redisFailed) {
                try {
                    commands.del(responseQueue);
                } catch (RedisException e) {
                    // Never hide the call's own outcome.
                }
            }
        }
    }

    @Override
    public <T> T call(String methodName, Object request) {
        return call(methodName, request, defaultMaxQueueDepth);
    }

    @Override
    public <T> T call(String methodName, Object request, long maxQueueDepth) {
        return call(methodName, request, (Long) maxQueueDepth);
    }

    private <T> T call(String methodName, Object request, Long maxQueueDepth) {
        Class<?> resolvedType = registry.get(methodName);
        if (resolvedType == null) {
            throw new AnyCallError(
                "No response type registered for operation '" + methodName + "'. "
                    + "Either call with explicit type: call(\"" + methodName + "\", req, YourType), "
                    + "or register the type first: registerType(\"" + methodName + "\", YourType)."
            );
        }
        @SuppressWarnings("unchecked")
        T result = (T) call(methodName, request, resolvedType, maxQueueDepth);
        return result;
    }

    @Override
    public Map<String, Object> rawCall(String methodName, Object request) {
        return rawCall(methodName, request, defaultMaxQueueDepth);
    }

    @Override
    public Map<String, Object> rawCall(String methodName, Object request, long maxQueueDepth) {
        return rawCall(methodName, request, (Long) maxQueueDepth);
    }

    private Map<String, Object> rawCall(String methodName, Object request, Long maxQueueDepth) {
        @SuppressWarnings("unchecked")
        Map<String, Object> result = (Map<String, Object>) call(methodName, request, Map.class, maxQueueDepth);
        return result;
    }

    @Override
    public long getQueueDepth(String methodName) {
        String requestQueue = AnycallQueues.REQUEST_QUEUE_PREFIX + methodName;
        return commands.llen(requestQueue);
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
     * Fails fast, before publishing, if no server has heartbeated recently enough to be
     * considered alive. Mirrors a connection-refused error over plain HTTP: without this,
     * a request would be queued and the caller would silently wait out the full timeout
     * with no server around to ever pop it.
     *
     * @throws dev.kaiquebt.anycall.exception.NoServerAvailableError if no server is alive
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

    /**
     * Waits for the call's response, up to the client's timeout (forever if it's zero), in
     * slices of {@link #WAITER_REAP_SLICE}. Returns null once the timeout is up.
     * <p>
     * A slice that ends empty reaps dead servers (see {@link #reap}), so a request whose
     * server died is failed back even when no other server is alive to notice.
     */
    private String readResponse(String queueKey) {
        long deadline = timeout.isZero() ? 0 : System.nanoTime() + timeout.toNanos();
        while (true) {
            long waitSeconds = WAITER_REAP_SLICE.getSeconds();
            if (deadline != 0) {
                long remaining = deadline - System.nanoTime();
                if (remaining <= 0) {
                    return null;
                }
                // Whole seconds, rounded up: Redis before 6.0 rejects a fractional timeout,
                // and 0 would mean forever. The call may end up to 1s late.
                long remainingSeconds = (remaining + 999_999_999L) / 1_000_000_000L;
                waitSeconds = Math.min(waitSeconds, remainingSeconds);
            }
            KeyValue<String, String> entry = commands.brpop(waitSeconds, queueKey);
            if (entry != null) {
                return entry.getValue();
            }
            reap();
        }
    }

    /**
     * Fails back the requests of every server that stopped heartbeating: the same work a
     * server does on its heartbeat, one script call when no server is dead. Failures only
     * log; the call goes back to waiting either way.
     */
    private void reap() {
        try {
            RedisCommands<String, String> reap = reapCommands();
            AnycallReaping.reapDeadServers(reap, AnycallReaping.staleServers(reap));
        } catch (Exception e) {
            log.warn("Failed to reap dead servers: {}", e.getMessage());
        }
    }

    private RedisCommands<String, String> reapCommands() {
        StatefulRedisConnection<String, String> current = reapConnection;
        if (current == null) {
            synchronized (this) {
                current = reapConnection;
                if (current == null) {
                    current = redisClient.connect();
                    reapConnection = current;
                }
            }
        }
        return current.sync();
    }
}
