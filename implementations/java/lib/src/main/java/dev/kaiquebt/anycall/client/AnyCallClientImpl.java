package dev.kaiquebt.anycall.client;

import com.fasterxml.jackson.databind.ObjectMapper;
import dev.kaiquebt.anycall.core.AnyCallClient;
import dev.kaiquebt.anycall.exception.*;
import dev.kaiquebt.anycall.model.AnyCallRequest;
import dev.kaiquebt.anycall.model.AnyCallResponse;
import dev.kaiquebt.anycall.publisher.AnycallQueues;
import dev.kaiquebt.anycall.registry.TypeRegistry;
import io.lettuce.core.RedisClient;
import io.lettuce.core.XReadArgs;
import io.lettuce.core.api.StatefulRedisConnection;
import io.lettuce.core.api.sync.RedisCommands;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.time.Duration;
import java.util.Collections;
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
    private static final Duration DEFAULT_TIMEOUT = Duration.ofSeconds(30);
    private static final String DATA_FIELD = "data";
    private static final ObjectMapper OBJECT_MAPPER = new ObjectMapper();

    private final StatefulRedisConnection<String, String> connection;
    private final RedisCommands<String, String> commands;
    private final Duration timeout;
    private final boolean metricsEnabled;
    private final TypeRegistry registry;

    public AnyCallClientImpl(String redisUri, Duration timeout, boolean metricsEnabled) {
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

        RedisClient client = RedisClient.create(redisUri);
        this.connection = client.connect();
        this.commands = connection.sync();
    }

    /**
     * Makes a synchronous remote procedure call via Redis.
     * Serializes the request, publishes it to the appropriate request stream,
     * waits for the response on a dedicated stream, and deserializes the result.
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
        long startTime = metricsEnabled ? System.currentTimeMillis() : 0;
        String _requestId = null;
        String responseStream = null;

        try {
            if (metricsEnabled) {
                log.debug("[METRICS] [CLIENT] Starting call to method: {}", methodName);
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
            String requestStream = AnycallQueues.REQUEST_QUEUE_PREFIX + methodName;
            commands.xadd(requestStream, Collections.singletonMap(DATA_FIELD, requestJson));

            if (metricsEnabled) {
                log.debug("[METRICS] [CLIENT] [{}] Request published to stream in {}ms", requestId,
                    System.currentTimeMillis() - beforePush);
            }

            responseStream = AnycallQueues.RESPONSE_QUEUE_PREFIX + requestId;
            long beforeWait = metricsEnabled ? System.currentTimeMillis() : 0;

            List<Object> records = readStream(responseStream, timeout);

            if (metricsEnabled) {
                log.debug("[METRICS] [CLIENT] [{}] Response received after {}ms", requestId,
                    System.currentTimeMillis() - beforeWait);
            }

            if (records == null || records.isEmpty()) {
                throw new TimeoutError(
                    methodName,
                    "Timeout waiting for response from method: " + methodName,
                    timeout.toMillis(),
                    requestId,
                    System.currentTimeMillis() + timeout.toMillis()
                );
            }

            long beforeDeserialize = metricsEnabled ? System.currentTimeMillis() : 0;
            Map<String, String> data = (Map<String, String>) records.get(1);
            String responseJson = data.get(DATA_FIELD);
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
            if (responseStream != null) {
                commands.del(responseStream);
            }
        }
    }

    @Override
    public <T> T call(String methodName, Object request) {
        Class<?> resolvedType = registry.get(methodName);
        if (resolvedType == null) {
            throw new AnyCallError(
                "No response type registered for operation '" + methodName + "'. "
                    + "Either call with explicit type: call(\"" + methodName + "\", req, YourType), "
                    + "or register the type first: registerType(\"" + methodName + "\", YourType)."
            );
        }
        @SuppressWarnings("unchecked")
        T result = (T) callInternal(methodName, request, resolvedType);
        return result;
    }

    @Override
    public Map<String, Object> callRaw(String methodName, Object request) {
        @SuppressWarnings("unchecked")
        Map<String, Object> result = (Map<String, Object>) callInternal(methodName, request, Map.class);
        return result;
    }

    @Override
    public void registerType(String operation, Class<?> responseType) {
        registry.register(operation, responseType);
    }

    private <T> T callInternal(String methodName, Object request, Class<T> responseType) {
        return call(methodName, request, responseType);
    }

    private List<Object> readStream(String streamKey, Duration timeout) {
        try {
            XReadArgs args = new XReadArgs();
            args.block(timeout);
            XReadArgs.StreamOffset<String> offset = XReadArgs.StreamOffset.from(streamKey, "0-0");
            List<io.lettuce.core.StreamMessage<String, String>> result = commands.xread(args, offset);

            if (result != null && !result.isEmpty()) {
                io.lettuce.core.StreamMessage<String, String> msg = result.get(0);
                return List.of(msg.getId(), msg.getBody());
            }
            return null;
        } catch (Exception e) {
            return null;
        }
    }
}
