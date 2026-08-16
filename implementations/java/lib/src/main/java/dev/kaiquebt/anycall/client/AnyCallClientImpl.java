package dev.kaiquebt.anycall.client;

import com.fasterxml.jackson.databind.ObjectMapper;
import dev.kaiquebt.anycall.core.AnyCallClient;
import dev.kaiquebt.anycall.exception.*;
import dev.kaiquebt.anycall.model.AnyCallRequest;
import dev.kaiquebt.anycall.model.AnyCallResponse;
import dev.kaiquebt.anycall.publisher.AnycallQueues;
import dev.kaiquebt.anycall.registry.TypeRegistry;
import io.lettuce.core.KeyValue;
import io.lettuce.core.RedisClient;
import io.lettuce.core.api.StatefulRedisConnection;
import io.lettuce.core.api.sync.RedisCommands;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.time.Duration;
import java.util.Map;

/**
 * Internal implementation of AnyCallClient.
 * <p>
 * <strong>This class is not intended for direct use. Use {@link dev.kaiquebt.anycall.core.AnyCall#client(String)} instead.</strong>
 * </p>
 */
public class AnyCallClientImpl implements AnyCallClient {

    private static final Logger log = LoggerFactory.getLogger(AnyCallClientImpl.class);
    private static final Duration DEFAULT_TIMEOUT = Duration.ofSeconds(30);
    private static final ObjectMapper OBJECT_MAPPER = new ObjectMapper();

    private final StatefulRedisConnection<String, String> connection;
    private final RedisCommands<String, String> commands;
    private final Duration timeout;
    private final boolean metricsEnabled;
    private final TypeRegistry registry;
    private volatile Long defaultMaxQueueDepth;

    public AnyCallClientImpl(String redisUri, Duration timeout, boolean metricsEnabled) {
        this(redisUri, timeout, metricsEnabled, null);
    }

    public AnyCallClientImpl(String redisUri, Duration timeout, boolean metricsEnabled, Long defaultMaxQueueDepth) {
        if (redisUri == null || redisUri.isEmpty()) {
            throw new IllegalArgumentException("AnyCall Client: redisUri must not be null or blank");
        }
        if (timeout == null) {
            this.timeout = DEFAULT_TIMEOUT;
        } else {
            this.timeout = timeout;
        }
        this.metricsEnabled = metricsEnabled;
        this.registry = new TypeRegistry();
        this.defaultMaxQueueDepth = defaultMaxQueueDepth;

        RedisClient client = RedisClient.create(redisUri);
        this.connection = client.connect();
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
        long startTime = metricsEnabled ? System.currentTimeMillis() : 0;
        String _requestId = null;
        String responseQueue = null;

        try {
            if (metricsEnabled) {
                log.debug("[METRICS] [CLIENT] Starting call to method: {}", methodName);
            }

            String requestQueue = AnycallQueues.REQUEST_QUEUE_PREFIX + methodName;

            if (maxQueueDepth != null) {
                long queueDepth = commands.llen(requestQueue);
                if (queueDepth >= maxQueueDepth) {
                    throw new QueueFullError(methodName, queueDepth, maxQueueDepth);
                }
            }

            String payload = OBJECT_MAPPER.writeValueAsString(request);
            AnyCallRequest anyCallRequest = AnyCallRequest.create(methodName, payload);
            String requestId = anyCallRequest.requestId();
            _requestId = requestId;
            String requestJson = OBJECT_MAPPER.writeValueAsString(anyCallRequest);

            if (metricsEnabled) {
                log.debug("[METRICS] [CLIENT] [{}] Request serialized in {}ms", requestId,
                    System.currentTimeMillis() - startTime);
            }

            long beforePush = metricsEnabled ? System.currentTimeMillis() : 0;
            commands.lpush(requestQueue, requestJson);

            if (metricsEnabled) {
                log.debug("[METRICS] [CLIENT] [{}] Request published to queue in {}ms", requestId,
                    System.currentTimeMillis() - beforePush);
            }

            responseQueue = AnycallQueues.RESPONSE_QUEUE_PREFIX + requestId;
            long beforeWait = metricsEnabled ? System.currentTimeMillis() : 0;

            String responseJson = readResponse(responseQueue, timeout);

            if (metricsEnabled) {
                log.debug("[METRICS] [CLIENT] [{}] Response received after {}ms", requestId,
                    System.currentTimeMillis() - beforeWait);
            }

            if (responseJson == null) {
                throw new TimeoutError(
                    methodName,
                    "Timeout waiting for response from method: " + methodName,
                    timeout.toMillis(),
                    requestId,
                    System.currentTimeMillis() + timeout.toMillis()
                );
            }

            long beforeDeserialize = metricsEnabled ? System.currentTimeMillis() : 0;
            AnyCallResponse response = OBJECT_MAPPER.readValue(responseJson, AnyCallResponse.class);

            if (response.hasError()) {
                throw new RemoteException(methodName, response.error(), "RemoteExecutionError");
            }

            T result = OBJECT_MAPPER.readValue(response.payload(), responseType);

            if (metricsEnabled) {
                log.debug("[METRICS] [CLIENT] [{}] Response deserialized in {}ms", requestId,
                    System.currentTimeMillis() - beforeDeserialize);
                log.debug("[METRICS] [CLIENT] [{}] Total call duration: {}ms", requestId,
                    System.currentTimeMillis() - startTime);
            }

            return result;
        } catch (Exception e) {
            if (metricsEnabled && _requestId != null) {
                log.error("[METRICS] [CLIENT] [{}] Call failed after {}ms: {}", _requestId,
                    System.currentTimeMillis() - startTime, e.getMessage());
            }
            if (e instanceof AnyCallError) {
                throw (AnyCallError) e;
            }
            if (e instanceof com.fasterxml.jackson.core.JsonProcessingException) {
                throw new SerializationError(methodName, "Failed to serialize/deserialize method call: " + methodName, e);
            }
            throw new AnyCallError(methodName, "Failed to call method: " + methodName, e);
        } finally {
            if (responseQueue != null) {
                commands.del(responseQueue);
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

    private String readResponse(String queueKey, Duration timeout) {
        try {
            KeyValue<String, String> entry = commands.brpop(timeout.getSeconds(), queueKey);
            return entry != null ? entry.getValue() : null;
        } catch (Exception e) {
            return null;
        }
    }
}
