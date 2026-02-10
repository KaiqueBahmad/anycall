package kaiquebt.dev.anycall.impl;

import com.fasterxml.jackson.databind.ObjectMapper;
import kaiquebt.dev.anycall.AnyCallClient;
import kaiquebt.dev.anycall.AnyCallException;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.data.redis.core.StringRedisTemplate;

import java.time.Duration;
import java.util.concurrent.TimeUnit;

/**
 * Default implementation of AnyCallClient.
 */
public class AnyCallClientImpl implements AnyCallClient {

    private static final Logger log = LoggerFactory.getLogger(AnyCallClientImpl.class);
    private static final Duration DEFAULT_TIMEOUT = Duration.ofSeconds(30);

    private final StringRedisTemplate redisTemplate;
    private final ObjectMapper objectMapper;
    private final Duration timeout;
    private final boolean metricsEnabled;

    public AnyCallClientImpl(StringRedisTemplate redisTemplate, ObjectMapper objectMapper) {
        this(redisTemplate, objectMapper, DEFAULT_TIMEOUT, false);
    }

    public AnyCallClientImpl(StringRedisTemplate redisTemplate, ObjectMapper objectMapper, Duration timeout) {
        this(redisTemplate, objectMapper, timeout, false);
    }

    public AnyCallClientImpl(StringRedisTemplate redisTemplate, ObjectMapper objectMapper, Duration timeout, boolean metricsEnabled) {
        this.redisTemplate = redisTemplate;
        this.objectMapper = objectMapper;
        this.timeout = timeout;
        this.metricsEnabled = metricsEnabled;
    }

    @Override
    public <T> T call(String methodName, Object request, Class<T> responseType) {
        long startTime = metricsEnabled ? System.currentTimeMillis() : 0;
        String requestId = null;

        try {
            if (metricsEnabled) {
                log.info("[METRICS] [CLIENT] Starting call to method: {}", methodName);
            }

            // Serialize the request payload
            String payload = objectMapper.writeValueAsString(request);

            // Create the request
            AnyCallRequest anyCallRequest = AnyCallRequest.create(methodName, payload);
            requestId = anyCallRequest.requestId();
            String requestJson = objectMapper.writeValueAsString(anyCallRequest);

            if (metricsEnabled) {
                long serializationTime = System.currentTimeMillis() - startTime;
                log.info("[METRICS] [CLIENT] [{}] Request serialized in {}ms", requestId, serializationTime);
            }

            // Push to the request queue
            long beforePush = metricsEnabled ? System.currentTimeMillis() : 0;
            String requestQueue = AnycallQueues.REQUEST_QUEUE_PREFIX + methodName;
            redisTemplate.opsForList().rightPush(requestQueue, requestJson);

            if (metricsEnabled) {
                long pushTime = System.currentTimeMillis() - beforePush;
                log.info("[METRICS] [CLIENT] [{}] Request pushed to queue in {}ms", requestId, pushTime);
            }

            // Wait for response
            long beforeWait = metricsEnabled ? System.currentTimeMillis() : 0;
            String responseQueue = AnycallQueues.RESPONSE_QUEUE_PREFIX + anyCallRequest.requestId();
            String responseJson = redisTemplate.opsForList().leftPop(
                responseQueue,
                timeout.getSeconds(),
                TimeUnit.SECONDS
            );

            if (responseJson == null) {
                throw new AnyCallException("Timeout waiting for response from method: " + methodName);
            }

            if (metricsEnabled) {
                long waitTime = System.currentTimeMillis() - beforeWait;
                log.info("[METRICS] [CLIENT] [{}] Response received after {}ms", requestId, waitTime);
            }

            // Deserialize response
            long beforeDeserialize = metricsEnabled ? System.currentTimeMillis() : 0;
            AnyCallResponse response = objectMapper.readValue(responseJson, AnyCallResponse.class);

            if (response.hasError()) {
                throw new AnyCallException("Error from remote method: " + response.error());
            }

            // Deserialize the payload
            T result = objectMapper.readValue(response.payload(), responseType);

            if (metricsEnabled) {
                long deserializationTime = System.currentTimeMillis() - beforeDeserialize;
                long totalTime = System.currentTimeMillis() - startTime;
                log.info("[METRICS] [CLIENT] [{}] Response deserialized in {}ms", requestId, deserializationTime);
                log.info("[METRICS] [CLIENT] [{}] Total call duration: {}ms", requestId, totalTime);
            }

            return result;
        } catch (Exception e) {
            if (metricsEnabled && requestId != null) {
                long totalTime = System.currentTimeMillis() - startTime;
                log.error("[METRICS] [CLIENT] [{}] Call failed after {}ms: {}", requestId, totalTime, e.getMessage());
            }
            if (e instanceof AnyCallException) {
                throw (AnyCallException) e;
            }
            throw new AnyCallException("Failed to call method: " + methodName, e);
        }
    }
}
