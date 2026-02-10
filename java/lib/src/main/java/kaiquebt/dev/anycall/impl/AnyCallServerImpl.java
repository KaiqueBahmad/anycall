package kaiquebt.dev.anycall.impl;

import com.fasterxml.jackson.databind.ObjectMapper;
import kaiquebt.dev.anycall.AnyCallServer;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.data.redis.core.StringRedisTemplate;

import java.util.HashMap;
import java.util.Map;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;

/**
 * Default implementation of AnyCallServer.
 */
public class AnyCallServerImpl implements AnyCallServer {

    private static final Logger log = LoggerFactory.getLogger(AnyCallServerImpl.class);

    private final StringRedisTemplate redisTemplate;
    private final ObjectMapper objectMapper;
    private final String group;
    private final Map<String, MethodHandler> methodHandlers;
    private final ExecutorService executorService;
    private final AtomicBoolean running;
    private final boolean metricsEnabled;

    public AnyCallServerImpl(
        StringRedisTemplate redisTemplate,
        ObjectMapper objectMapper,
        String group,
        Map<String, MethodHandler> methodHandlers
    ) {
        this(redisTemplate, objectMapper, group, methodHandlers, false);
    }

    public AnyCallServerImpl(
        StringRedisTemplate redisTemplate,
        ObjectMapper objectMapper,
        String group,
        Map<String, MethodHandler> methodHandlers,
        boolean metricsEnabled
    ) {
        this.redisTemplate = redisTemplate;
        this.objectMapper = objectMapper;
        this.group = group;
        this.methodHandlers = new HashMap<>(methodHandlers);
        this.executorService = Executors.newFixedThreadPool(methodHandlers.size());
        this.running = new AtomicBoolean(false);
        this.metricsEnabled = metricsEnabled;
    }

    @Override
    public AnyCallServer start() {
        if (running.compareAndSet(false, true)) {
            log.info("Starting AnyCall server for group: {}", group);
            log.info("Registered methods: {}", methodHandlers.keySet());

            for (Map.Entry<String, MethodHandler> entry : methodHandlers.entrySet()) {
                String methodName = entry.getKey();
                MethodHandler handler = entry.getValue();
                executorService.submit(() -> processRequests(methodName, handler));
            }
        }
        return this;
    }

    @Override
    public void stop() {
        if (running.compareAndSet(true, false)) {
            log.info("Stopping AnyCall server for group: {}", group);
            executorService.shutdown();
            try {
                if (!executorService.awaitTermination(5, TimeUnit.SECONDS)) {
                    executorService.shutdownNow();
                }
            } catch (InterruptedException e) {
                executorService.shutdownNow();
                Thread.currentThread().interrupt();
            }
        }
    }

    @Override
    public boolean isRunning() {
        return running.get();
    }

    private void processRequests(String methodName, MethodHandler handler) {
        String requestQueue = AnycallQueues.REQUEST_QUEUE_PREFIX + methodName;
        log.info("Worker started for method: {} on queue: {}", methodName, requestQueue);

        while (running.get()) {
            try {
                // Block and wait for a request (timeout 1 second to check running flag)
                String requestJson = redisTemplate.opsForList().leftPop(
                    requestQueue,
                    1,
                    TimeUnit.SECONDS
                );

                if (requestJson != null) {
                    processRequest(requestJson, handler);
                }

            } catch (Exception e) {
                log.error("Error processing request for method: {}", methodName, e);
            }
        }

        log.info("Worker stopped for method: {}", methodName);
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
            String responseQueue = AnycallQueues.RESPONSE_QUEUE_PREFIX + response.requestId();
            String responseJson = objectMapper.writeValueAsString(response);
            redisTemplate.opsForList().rightPush(responseQueue, responseJson);

            // Set expiration on the response queue (1 minute)
            redisTemplate.expire(responseQueue, 1, TimeUnit.MINUTES);

        } catch (Exception e) {
            log.error("Error sending response: {}", response.requestId(), e);
        }
    }
}
