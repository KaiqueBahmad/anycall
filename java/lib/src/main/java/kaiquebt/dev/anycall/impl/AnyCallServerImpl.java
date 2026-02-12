package kaiquebt.dev.anycall.impl;

import com.fasterxml.jackson.databind.ObjectMapper;
import kaiquebt.dev.anycall.AnyCallServer;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.data.redis.connection.RedisConnectionFactory;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.listener.ChannelTopic;
import org.springframework.data.redis.listener.RedisMessageListenerContainer;

import java.util.HashMap;
import java.util.Map;
import java.util.concurrent.atomic.AtomicBoolean;

/**
 * Default implementation of AnyCallServer using Redis pub/sub.
 */
public class AnyCallServerImpl implements AnyCallServer {

    private static final Logger log = LoggerFactory.getLogger(AnyCallServerImpl.class);

    private final StringRedisTemplate redisTemplate;
    private final ObjectMapper objectMapper;
    private final String group;
    private final Map<String, MethodHandler> methodHandlers;
    private final RedisMessageListenerContainer listenerContainer;
    private final AtomicBoolean running;
    private final boolean metricsEnabled;

    public AnyCallServerImpl(
        StringRedisTemplate redisTemplate,
        ObjectMapper objectMapper,
        String group,
        Map<String, MethodHandler> methodHandlers,
        RedisConnectionFactory connectionFactory
    ) {
        this(redisTemplate, objectMapper, group, methodHandlers, connectionFactory, false);
    }

    public AnyCallServerImpl(
        StringRedisTemplate redisTemplate,
        ObjectMapper objectMapper,
        String group,
        Map<String, MethodHandler> methodHandlers,
        RedisConnectionFactory connectionFactory,
        boolean metricsEnabled
    ) {
        this.redisTemplate = redisTemplate;
        this.objectMapper = objectMapper;
        this.group = group;
        this.methodHandlers = new HashMap<>(methodHandlers);
        this.running = new AtomicBoolean(false);
        this.metricsEnabled = metricsEnabled;

        // Create listener container
        this.listenerContainer = new RedisMessageListenerContainer();
        this.listenerContainer.setConnectionFactory(connectionFactory);

        // Register listeners for each method
        for (Map.Entry<String, MethodHandler> entry : methodHandlers.entrySet()) {
            String methodName = entry.getKey();
            MethodHandler handler = entry.getValue();
            String channelName = AnycallQueues.REQUEST_QUEUE_PREFIX + methodName;

            listenerContainer.addMessageListener((message, pattern) -> {
                processRequest(new String(message.getBody()), handler);
            }, new ChannelTopic(channelName));

            log.info("Registered listener for method: {} on channel: {}", methodName, channelName);
        }
    }

    @Override
    public AnyCallServer start() {
        if (running.compareAndSet(false, true)) {
            log.info("Starting AnyCall server for group: {}", group);
            log.info("Registered methods: {}", methodHandlers.keySet());
            try {
                listenerContainer.afterPropertiesSet();
                listenerContainer.start();
            } catch (Exception e) {
                running.set(false);
                throw new RuntimeException("Failed to start AnyCall server", e);
            }
        }
        return this;
    }

    @Override
    public void stop() {
        if (running.compareAndSet(true, false)) {
            log.info("Stopping AnyCall server for group: {}", group);
            listenerContainer.stop();
            try {
                listenerContainer.destroy();
            } catch (Exception e) {
                e.printStackTrace();
            }
        }
    }

    @Override
    public boolean isRunning() {
        return running.get();
    }

    private void processRequest(String requestJson, MethodHandler handler) {
        long startTime = metricsEnabled ? System.currentTimeMillis() : 0;
        String requestId = null;
        String methodName = null;

        try {
            // Deserialize the request
            long beforeDeserialize = metricsEnabled ? System.currentTimeMillis() : 0;
            AnyCallRequest request = objectMapper.readValue(requestJson, AnyCallRequest.class);
            requestId = request.requestId();
            methodName = request.methodName();

            if (metricsEnabled) {
                long deserializeTime = System.currentTimeMillis() - beforeDeserialize;
                log.info("[METRICS] [SERVER] [{}] Request deserialized in {}ms", requestId, deserializeTime);
            } else {
                log.info("Processing request: {} for method: {}", requestId, methodName);
            }

            // Deserialize the payload
            long beforePayloadDeserialize = metricsEnabled ? System.currentTimeMillis() : 0;
            Object parameter = objectMapper.readValue(request.payload(), handler.parameterType());

            if (metricsEnabled) {
                long payloadDeserializeTime = System.currentTimeMillis() - beforePayloadDeserialize;
                log.info("[METRICS] [SERVER] [{}] Payload deserialized in {}ms", requestId, payloadDeserializeTime);
            }

            // Invoke the method
            long beforeInvoke = metricsEnabled ? System.currentTimeMillis() : 0;
            Object result = handler.method().invoke(handler.bean(), parameter);

            if (metricsEnabled) {
                long invokeTime = System.currentTimeMillis() - beforeInvoke;
                log.info("[METRICS] [SERVER] [{}] Method '{}' executed in {}ms", requestId, methodName, invokeTime);
            }

            // Serialize the result
            long beforeSerialize = metricsEnabled ? System.currentTimeMillis() : 0;
            String resultJson = objectMapper.writeValueAsString(result);

            if (metricsEnabled) {
                long serializeTime = System.currentTimeMillis() - beforeSerialize;
                log.info("[METRICS] [SERVER] [{}] Result serialized in {}ms", requestId, serializeTime);
            }

            // Send the response
            long beforeSend = metricsEnabled ? System.currentTimeMillis() : 0;
            AnyCallResponse response = AnyCallResponse.success(requestId, resultJson);
            sendResponse(response);

            if (metricsEnabled) {
                long sendTime = System.currentTimeMillis() - beforeSend;
                long totalTime = System.currentTimeMillis() - startTime;
                log.info("[METRICS] [SERVER] [{}] Response sent in {}ms", requestId, sendTime);
                log.info("[METRICS] [SERVER] [{}] Total processing time: {}ms", requestId, totalTime);
            } else {
                log.info("Request {} processed successfully", requestId);
            }

        } catch (Exception e) {
            if (metricsEnabled && requestId != null) {
                long totalTime = System.currentTimeMillis() - startTime;
                log.error("[METRICS] [SERVER] [{}] Processing failed after {}ms: {}", requestId, totalTime, e.getMessage());
            }
            log.error("Error processing request: {}", requestId, e);
            if (requestId != null) {
                AnyCallResponse response = AnyCallResponse.error(
                    requestId,
                    e.getMessage() != null ? e.getMessage() : e.getClass().getName()
                );
                sendResponse(response);
            }
        }
    }

    private void sendResponse(AnyCallResponse response) {
        try {
            String responseChannel = AnycallQueues.RESPONSE_QUEUE_PREFIX + response.requestId();
            String responseJson = objectMapper.writeValueAsString(response);
            redisTemplate.convertAndSend(responseChannel, responseJson);

        } catch (Exception e) {
            log.error("Error sending response: {}", response.requestId(), e);
        }
    }
}
