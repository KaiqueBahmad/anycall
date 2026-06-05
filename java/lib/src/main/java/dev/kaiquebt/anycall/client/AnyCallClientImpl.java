package dev.kaiquebt.anycall.client;

import com.fasterxml.jackson.databind.ObjectMapper;
import dev.kaiquebt.anycall.core.AnyCallClient;
import dev.kaiquebt.anycall.exception.AnyCallException;
import dev.kaiquebt.anycall.model.AnyCallRequest;
import dev.kaiquebt.anycall.model.AnyCallResponse;
import dev.kaiquebt.anycall.publisher.AnycallQueues;
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

public class AnyCallClientImpl implements AnyCallClient {

    private static final Logger log = LoggerFactory.getLogger(AnyCallClientImpl.class);
    private static final Duration DEFAULT_TIMEOUT = Duration.ofSeconds(30);
    private static final String DATA_FIELD = "data";
    private static final ObjectMapper OBJECT_MAPPER = new ObjectMapper();

    private final StatefulRedisConnection<String, String> connection;
    private final RedisCommands<String, String> commands;
    private final Duration timeout;
    private final boolean metricsEnabled;

    public AnyCallClientImpl(String redisUri) {
        this(redisUri, DEFAULT_TIMEOUT, false);
    }

    public AnyCallClientImpl(String redisUri, Duration timeout) {
        this(redisUri, timeout, false);
    }

    public AnyCallClientImpl(String redisUri, Duration timeout, boolean metricsEnabled) {
        this.timeout = timeout;
        this.metricsEnabled = metricsEnabled;

        String actualUri = redisUri != null ? redisUri : "redis://localhost:6379";
        RedisClient client = RedisClient.create(actualUri);
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
                throw new AnyCallException("Timeout waiting for response from method: " + methodName);
            }

            long beforeDeserialize = metricsEnabled ? System.currentTimeMillis() : 0;
            Map<String, String> data = (Map<String, String>) records.get(1);
            String responseJson = data.get(DATA_FIELD);
            AnyCallResponse response = OBJECT_MAPPER.readValue(responseJson, AnyCallResponse.class);

            if (response.hasError()) {
                throw new AnyCallException("Error from remote method: " + response.error());
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
            if (e instanceof AnyCallException) {
                throw (AnyCallException) e;
            }
            throw new AnyCallException("Failed to call method: " + methodName, e);
        } finally {
            if (responseStream != null) {
                commands.del(responseStream);
            }
        }
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
