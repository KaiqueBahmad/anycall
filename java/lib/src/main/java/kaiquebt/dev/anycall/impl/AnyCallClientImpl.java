package kaiquebt.dev.anycall.impl;

import com.fasterxml.jackson.databind.ObjectMapper;
import kaiquebt.dev.anycall.AnyCallClient;
import kaiquebt.dev.anycall.AnyCallException;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.data.redis.connection.RedisConnectionFactory;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.listener.ChannelTopic;
import org.springframework.data.redis.listener.RedisMessageListenerContainer;

import java.time.Duration;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.TimeUnit;

/**
 * Default implementation of AnyCallClient using Redis pub/sub.
 */
public class AnyCallClientImpl implements AnyCallClient {

    private static final Logger log = LoggerFactory.getLogger(AnyCallClientImpl.class);
    private static final Duration DEFAULT_TIMEOUT = Duration.ofSeconds(30);

    private final StringRedisTemplate redisTemplate;
    private final ObjectMapper objectMapper;
    private final Duration timeout;
    private final boolean metricsEnabled;
    private final RedisMessageListenerContainer listenerContainer;
    private final ConcurrentHashMap<String, CompletableFuture<String>> pendingRequests;

    public AnyCallClientImpl(StringRedisTemplate redisTemplate, ObjectMapper objectMapper, RedisConnectionFactory connectionFactory) {
        this(redisTemplate, objectMapper, connectionFactory, DEFAULT_TIMEOUT, false);
    }

    public AnyCallClientImpl(StringRedisTemplate redisTemplate, ObjectMapper objectMapper, RedisConnectionFactory connectionFactory, Duration timeout) {
        this(redisTemplate, objectMapper, connectionFactory, timeout, false);
    }

    public AnyCallClientImpl(StringRedisTemplate redisTemplate, ObjectMapper objectMapper, RedisConnectionFactory connectionFactory, Duration timeout, boolean metricsEnabled) {
        this.redisTemplate = redisTemplate;
        this.objectMapper = objectMapper;
        this.timeout = timeout;
        this.metricsEnabled = metricsEnabled;
        this.pendingRequests = new ConcurrentHashMap<>();

        // Create listener container for responses
        this.listenerContainer = new RedisMessageListenerContainer();
        this.listenerContainer.setConnectionFactory(connectionFactory);
        try {
            this.listenerContainer.afterPropertiesSet();
            this.listenerContainer.start();
        } catch (Exception e) {
            throw new RuntimeException("Failed to initialize AnyCall client listener container", e);
        }
    }

    @Override
    public <T> T call(String methodName, Object request, Class<T> responseType) {
        long startTime = metricsEnabled ? System.currentTimeMillis() : 0;
        String _requestId = null;
        try {
            if (metricsEnabled) {
                log.info("[METRICS] [CLIENT] Starting call to method: {}", methodName);
            }

            // Serialize the request payload
            String payload = objectMapper.writeValueAsString(request);

            // Create the request
            AnyCallRequest anyCallRequest = AnyCallRequest.create(methodName, payload);
            String requestId = anyCallRequest.requestId();
            _requestId = requestId;
            String requestJson = objectMapper.writeValueAsString(anyCallRequest);

            if (metricsEnabled) {
                long serializationTime = System.currentTimeMillis() - startTime;
                log.info("[METRICS] [CLIENT] [{}] Request serialized in {}ms", requestId, serializationTime);
            }

            // Create a future for this request
            CompletableFuture<String> responseFuture = new CompletableFuture<>();
            pendingRequests.put(requestId, responseFuture);

            // Subscribe to response channel BEFORE publishing request
            String responseChannel = AnycallQueues.RESPONSE_QUEUE_PREFIX + requestId;
            listenerContainer.addMessageListener((message, pattern) -> {
                String responseJson = new String(message.getBody());
                CompletableFuture<String> future = pendingRequests.remove(requestId);
                if (future != null) {
                    future.complete(responseJson);
                }
            }, new ChannelTopic(responseChannel));

            // Publish to the request channel
            long beforePush = metricsEnabled ? System.currentTimeMillis() : 0;
            String requestChannel = AnycallQueues.REQUEST_QUEUE_PREFIX + methodName;
            redisTemplate.convertAndSend(requestChannel, requestJson);

            if (metricsEnabled) {
                long pushTime = System.currentTimeMillis() - beforePush;
                log.info("[METRICS] [CLIENT] [{}] Request published to channel in {}ms", requestId, pushTime);
            }

            // Wait for response
            long beforeWait = metricsEnabled ? System.currentTimeMillis() : 0;
            String responseJson;
            try {
                responseJson = responseFuture.get(timeout.getSeconds(), TimeUnit.SECONDS);
            } catch (java.util.concurrent.TimeoutException e) {
                pendingRequests.remove(requestId);
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
            if (metricsEnabled && _requestId != null) {
                long totalTime = System.currentTimeMillis() - startTime;
                log.error("[METRICS] [CLIENT] [{}] Call failed after {}ms: {}", _requestId, totalTime, e.getMessage());
            }
            if (e instanceof AnyCallException) {
                throw (AnyCallException) e;
            }
            throw new AnyCallException("Failed to call method: " + methodName, e);
        }
    }
}
