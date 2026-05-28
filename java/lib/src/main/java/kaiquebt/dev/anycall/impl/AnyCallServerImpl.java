package kaiquebt.dev.anycall.impl;

import com.fasterxml.jackson.databind.ObjectMapper;
import kaiquebt.dev.anycall.AnyCallServer;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.data.redis.connection.stream.*;
import org.springframework.data.redis.core.StringRedisTemplate;

import java.time.Duration;
import java.util.Collections;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;

public class AnyCallServerImpl implements AnyCallServer {

    private static final Logger log = LoggerFactory.getLogger(AnyCallServerImpl.class);
    private static final String DATA_FIELD = "data";
    private static final Duration POLL_BLOCK_TIMEOUT = Duration.ofSeconds(2);

    private final StringRedisTemplate redisTemplate;
    private final ObjectMapper objectMapper;
    private final String group;
    private final String consumerId;
    private final Map<String, MethodHandler> methodHandlers;
    private final AtomicBoolean running;
    private final boolean metricsEnabled;
    private ExecutorService executor;

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
        this.consumerId = group + "-" + UUID.randomUUID();
        this.methodHandlers = new HashMap<>(methodHandlers);
        this.running = new AtomicBoolean(false);
        this.metricsEnabled = metricsEnabled;
    }

    @Override
    public AnyCallServer start() {
        if (running.compareAndSet(false, true)) {
            log.info("Starting AnyCall server for group: {}", group);
            log.info("Registered methods: {}", methodHandlers.keySet());
            executor = Executors.newFixedThreadPool(methodHandlers.size());

            for (Map.Entry<String, MethodHandler> entry : methodHandlers.entrySet()) {
                String methodName = entry.getKey();
                MethodHandler handler = entry.getValue();
                String streamKey = AnycallQueues.REQUEST_QUEUE_PREFIX + methodName;

                ensureConsumerGroup(streamKey);
                log.info("Listening on stream: {}", streamKey);

                executor.submit(() -> pollStream(streamKey, handler));
            }
        }
        return this;
    }

    @Override
    public void stop() {
        if (running.compareAndSet(true, false)) {
            log.info("Stopping AnyCall server for group: {}", group);
            if (executor != null) {
                executor.shutdown();
                try {
                    if (!executor.awaitTermination(5, TimeUnit.SECONDS)) {
                        executor.shutdownNow();
                    }
                } catch (InterruptedException e) {
                    executor.shutdownNow();
                    Thread.currentThread().interrupt();
                }
            }
        }
    }

    @Override
    public boolean isRunning() {
        return running.get();
    }

    private void ensureConsumerGroup(String streamKey) {
        try {
            redisTemplate.opsForStream().createGroup(streamKey, ReadOffset.latest(), group);
            log.info("Created consumer group '{}' for stream: {}", group, streamKey);
        } catch (Exception e) {
            String msg = e.getMessage() != null ? e.getMessage() : "";
            if (msg.contains("BUSYGROUP")) {
                log.debug("Consumer group '{}' already exists for stream: {}", group, streamKey);
            } else {
                // Stream does not exist yet; seed it so XGROUP CREATE succeeds
                try {
                    RecordId initId = redisTemplate.opsForStream().add(
                        StreamRecords.newRecord().in(streamKey).ofMap(Collections.singletonMap("_init", "1"))
                    );
                    redisTemplate.opsForStream().delete(streamKey, initId.getValue());
                    redisTemplate.opsForStream().createGroup(streamKey, ReadOffset.latest(), group);
                    log.info("Created consumer group '{}' for stream: {}", group, streamKey);
                } catch (Exception ex) {
                    String exMsg = ex.getMessage() != null ? ex.getMessage() : "";
                    if (!exMsg.contains("BUSYGROUP")) {
                        log.warn("Could not create consumer group for stream {}: {}", streamKey, exMsg);
                    }
                }
            }
        }
    }

    @SuppressWarnings("unchecked")
    private void pollStream(String streamKey, MethodHandler handler) {
        Consumer consumer = Consumer.from(group, consumerId);
        StreamReadOptions readOptions = StreamReadOptions.empty().block(POLL_BLOCK_TIMEOUT).count(1);
        StreamOffset<String> offset = StreamOffset.create(streamKey, ReadOffset.lastConsumed());

        while (running.get()) {
            try {
                List<MapRecord<String, Object, Object>> records = redisTemplate.opsForStream()
                    .read(consumer, readOptions, offset);

                if (records != null) {
                    for (MapRecord<String, Object, Object> record : records) {
                        String requestJson = (String) record.getValue().get(DATA_FIELD);
                        processRequest(requestJson, handler);
                        redisTemplate.opsForStream().acknowledge(streamKey, group, record.getId());
                    }
                }
            } catch (Exception e) {
                if (running.get()) {
                    log.error("Error reading from stream {}: {}", streamKey, e.getMessage());
                }
            }
        }
    }

    private void processRequest(String requestJson, MethodHandler handler) {
        long startTime = metricsEnabled ? System.currentTimeMillis() : 0;
        String requestId = null;
        String methodName = null;

        try {
            long beforeDeserialize = metricsEnabled ? System.currentTimeMillis() : 0;
            AnyCallRequest request = objectMapper.readValue(requestJson, AnyCallRequest.class);
            requestId = request.requestId();
            methodName = request.methodName();

            if (metricsEnabled) {
                log.info("[METRICS] [SERVER] [{}] Request deserialized in {}ms", requestId,
                    System.currentTimeMillis() - beforeDeserialize);
            } else {
                log.info("Processing request: {} for method: {}", requestId, methodName);
            }

            long beforePayloadDeserialize = metricsEnabled ? System.currentTimeMillis() : 0;
            Object parameter = objectMapper.readValue(request.payload(), handler.parameterType());

            if (metricsEnabled) {
                log.info("[METRICS] [SERVER] [{}] Payload deserialized in {}ms", requestId,
                    System.currentTimeMillis() - beforePayloadDeserialize);
            }

            long beforeInvoke = metricsEnabled ? System.currentTimeMillis() : 0;
            Object result = handler.method().invoke(handler.bean(), parameter);

            if (metricsEnabled) {
                log.info("[METRICS] [SERVER] [{}] Method '{}' executed in {}ms", requestId, methodName,
                    System.currentTimeMillis() - beforeInvoke);
            }

            long beforeSerialize = metricsEnabled ? System.currentTimeMillis() : 0;
            String resultJson = objectMapper.writeValueAsString(result);

            if (metricsEnabled) {
                log.info("[METRICS] [SERVER] [{}] Result serialized in {}ms", requestId,
                    System.currentTimeMillis() - beforeSerialize);
            }

            long beforeSend = metricsEnabled ? System.currentTimeMillis() : 0;
            AnyCallResponse response = AnyCallResponse.success(requestId, resultJson);
            sendResponse(response);

            if (metricsEnabled) {
                log.info("[METRICS] [SERVER] [{}] Response sent in {}ms", requestId,
                    System.currentTimeMillis() - beforeSend);
                log.info("[METRICS] [SERVER] [{}] Total processing time: {}ms", requestId,
                    System.currentTimeMillis() - startTime);
            } else {
                log.info("Request {} processed successfully", requestId);
            }

        } catch (Exception e) {
            if (metricsEnabled && requestId != null) {
                log.error("[METRICS] [SERVER] [{}] Processing failed after {}ms: {}", requestId,
                    System.currentTimeMillis() - startTime, e.getMessage());
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
            String responseStream = AnycallQueues.RESPONSE_QUEUE_PREFIX + response.requestId();
            String responseJson = objectMapper.writeValueAsString(response);
            redisTemplate.opsForStream().add(
                StreamRecords.newRecord().in(responseStream).ofMap(Collections.singletonMap(DATA_FIELD, responseJson))
            );
        } catch (Exception e) {
            log.error("Error sending response: {}", response.requestId(), e);
        }
    }
}
