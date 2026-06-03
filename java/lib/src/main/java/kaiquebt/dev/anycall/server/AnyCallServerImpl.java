package kaiquebt.dev.anycall.server;

import com.fasterxml.jackson.databind.ObjectMapper;
import kaiquebt.dev.anycall.core.AnyCallServer;
import kaiquebt.dev.anycall.core.RedisStreamAdapter;
import kaiquebt.dev.anycall.exception.AnyCallException;
import kaiquebt.dev.anycall.model.AnyCallRequest;
import kaiquebt.dev.anycall.model.AnyCallResponse;
import kaiquebt.dev.anycall.publisher.AnycallQueues;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

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

/**
 * Implementation of the AnyCall server that processes remote procedure calls from Redis.
 * Manages a pool of worker threads that listen on Redis streams for incoming requests,
 * deserialize them, invoke the appropriate handler methods, and send back responses.
 * This implementation uses Redis Streams with consumer groups for reliable message processing.
 */
public class AnyCallServerImpl implements AnyCallServer {

    private static final Logger log = LoggerFactory.getLogger(AnyCallServerImpl.class);
    private static final String DATA_FIELD = "data";
    private static final Duration POLL_BLOCK_TIMEOUT = Duration.ofSeconds(5);

    private final RedisStreamAdapter redis;
    private final ObjectMapper objectMapper;
    private final String group;
    private final String consumerId;
    private final Map<String, MethodHandler> methodHandlers;
    private final AtomicBoolean running;
    private final boolean metricsEnabled;
    private ExecutorService executor;

    public AnyCallServerImpl(
        RedisStreamAdapter redis,
        ObjectMapper objectMapper,
        String group,
        Map<String, MethodHandler> methodHandlers
    ) {
        this(redis, objectMapper, group, methodHandlers, false);
    }

    public AnyCallServerImpl(
        RedisStreamAdapter redis,
        ObjectMapper objectMapper,
        String group,
        Map<String, MethodHandler> methodHandlers,
        boolean metricsEnabled
    ) {
        this.redis = redis;
        this.objectMapper = objectMapper;
        this.group = group;
        this.consumerId = group + "-" + UUID.randomUUID();
        this.methodHandlers = new HashMap<>(methodHandlers);
        this.running = new AtomicBoolean(false);
        this.metricsEnabled = metricsEnabled;
    }

    /**
     * Starts the server and begins processing incoming requests from Redis streams.
     * Creates worker threads for each registered method and listens on corresponding streams.
     * This method is idempotent - repeated calls have no effect if already running.
     *
     * @return this server instance for method chaining
     */
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

    /**
     * Stops the server and shuts down all worker threads.
     * Gracefully terminates the executor service with a timeout.
     * This method is idempotent - repeated calls have no effect if already stopped.
     */
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

    /**
     * Checks if the server is currently running and processing requests.
     *
     * @return {@code true} if the server is running, {@code false} otherwise
     */
    @Override
    public boolean isRunning() {
        return running.get();
    }

    /**
     * Ensures that a Redis consumer group exists for the given stream.
     * Creates the group if it doesn't exist, handling cases where the stream hasn't been created yet.
     *
     * @param streamKey the Redis stream key to ensure a consumer group for
     */
    private void ensureConsumerGroup(String streamKey) {
        try {
            redis.createGroup(streamKey, group);
            log.info("Created consumer group '{}' for stream: {}", group, streamKey);
        } catch (Exception e) {
            String msg = e.getMessage() != null ? e.getMessage() : "";
            if (msg.contains("BUSYGROUP")) {
                log.debug("Consumer group '{}' already exists for stream: {}", group, streamKey);
            } else {
                log.warn("Could not create consumer group for stream {}: {}", streamKey, msg);
            }
        }
    }

    /**
     * Continuously polls a Redis stream for new requests and processes them.
     * Runs in a dedicated thread and blocks when no messages are available.
     *
     * @param streamKey the Redis stream key to poll
     * @param handler the method handler for processing requests from this stream
     */
    private void pollStream(String streamKey, MethodHandler handler) {
        while (running.get()) {
            try {
                List<Object> records = redis.readGroup(streamKey, group, consumerId, POLL_BLOCK_TIMEOUT);

                if (records != null && records.size() >= 2) {
                    String messageId = (String) records.get(0);
                    Map<String, String> data = (Map<String, String>) records.get(1);
                    String requestJson = data.get(DATA_FIELD);

                    if (requestJson != null) {
                        processRequest(requestJson, handler);
                        redis.acknowledge(streamKey, group, messageId);
                    }
                }
            } catch (Exception e) {
                if (running.get()) {
                    log.error("Error reading from stream {}: {}", streamKey, e.getMessage());
                }
            }
        }
    }

    /**
     * Processes a single request by deserializing it, invoking the handler method, and sending the response.
     * Handles errors gracefully and sends error responses back to the client.
     * Collects detailed metrics if metrics are enabled.
     *
     * @param requestJson the JSON-serialized request
     * @param handler the method handler to invoke
     */
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

    /**
     * Sends a response back to the client via a Redis stream.
     * Serializes the response and pushes it to the client's response stream.
     *
     * @param response the response to send
     */
    private void sendResponse(AnyCallResponse response) {
        try {
            String responseStream = AnycallQueues.RESPONSE_QUEUE_PREFIX + response.requestId();
            String responseJson = objectMapper.writeValueAsString(response);
            redis.add(responseStream, Collections.singletonMap(DATA_FIELD, responseJson));
        } catch (Exception e) {
            log.error("Error sending response: {}", response.requestId(), e);
        }
    }
}
