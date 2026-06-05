package dev.kaiquebt.anycall.server;

import com.fasterxml.jackson.databind.ObjectMapper;
import dev.kaiquebt.anycall.annotation.Supply;
import dev.kaiquebt.anycall.core.AnyCallServer;
import dev.kaiquebt.anycall.model.AnyCallRequest;
import dev.kaiquebt.anycall.model.AnyCallResponse;
import dev.kaiquebt.anycall.publisher.AnycallQueues;
import io.lettuce.core.Consumer;
import io.lettuce.core.RedisClient;
import io.lettuce.core.XReadArgs;
import io.lettuce.core.api.StatefulRedisConnection;
import io.lettuce.core.api.sync.RedisCommands;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.lang.reflect.Method;
import java.time.Duration;
import java.util.Collections;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;

/**
 * Internal implementation of AnyCallServer.
 * <p>
 * <strong>This class is not intended for direct use. Use {@link dev.kaiquebt.anycall.core.AnyCall#server(String)} instead.</strong>
 * </p>
 * Manages a pool of worker threads that listen on Redis streams for incoming requests,
 * deserialize them, invoke the appropriate handler methods, and send back responses.
 * This implementation uses Redis Streams with consumer groups for reliable message processing.
 */
public class AnyCallServerImpl implements AnyCallServer {

    private static final Logger log = LoggerFactory.getLogger(AnyCallServerImpl.class);
    private static final String DATA_FIELD = "data";
    private static final String GROUP_PREFIX = "anycall-workers";
    private static final Duration POLL_BLOCK_TIMEOUT = Duration.ofSeconds(5);
    private static final ObjectMapper OBJECT_MAPPER = new ObjectMapper();

    private final StatefulRedisConnection<String, String> connection;
    private final RedisCommands<String, String> commands;
    private final Map<String, MethodHandler> methodHandlers;
    private final Map<String, Future<?>> methodThreads;
    private final AtomicBoolean running;
    private final boolean metricsEnabled;
    private ExecutorService executor;

    public AnyCallServerImpl(String redisUri, boolean metricsEnabled) {
        String actualUri = redisUri != null ? redisUri : "redis://localhost:6379";
        RedisClient client = RedisClient.create(actualUri);
        this.connection = client.connect();
        this.commands = connection.sync();
        this.methodHandlers = new ConcurrentHashMap<>();
        this.methodThreads = new ConcurrentHashMap<>();
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
            log.info("Starting AnyCall server");
            executor = Executors.newCachedThreadPool();
            startAllListeners();
        }
        return this;
    }

    public AnyCallServer register(Object supplier) {
        scanAndRegisterSupplier(supplier);
        if (running.get()) {
            startListenersForNewMethods();
        }
        return this;
    }

    public AnyCallServer register(Object... suppliers) {
        for (Object supplier : suppliers) {
            scanAndRegisterSupplier(supplier);
        }
        if (running.get()) {
            startListenersForNewMethods();
        }
        return this;
    }

    public AnyCallServer unregister(String methodName) {
        MethodHandler removed = methodHandlers.remove(methodName);
        if (removed != null) {
            Future<?> thread = methodThreads.remove(methodName);
            if (thread != null) {
                thread.cancel(true);
                log.info("Unregistered method: {}", methodName);
            }
        }
        return this;
    }

    private void startAllListeners() {
        log.info("Registered methods: {}", methodHandlers.keySet());
        for (Map.Entry<String, MethodHandler> entry : methodHandlers.entrySet()) {
            String methodName = entry.getKey();
            MethodHandler handler = entry.getValue();
            String streamKey = AnycallQueues.REQUEST_QUEUE_PREFIX + methodName;
            String group = GROUP_PREFIX + ":" + methodName;

            ensureConsumerGroup(streamKey, group);
            log.info("Listening on stream: {} with group: {}", streamKey, group);

            Future<?> future = executor.submit(() -> pollStream(streamKey, handler, group));
            methodThreads.put(methodName, future);
        }
    }

    private void startListenersForNewMethods() {
        Set<String> existingThreads = methodThreads.keySet();
        for (Map.Entry<String, MethodHandler> entry : methodHandlers.entrySet()) {
            String methodName = entry.getKey();
            if (!existingThreads.contains(methodName)) {
                MethodHandler handler = entry.getValue();
                String streamKey = AnycallQueues.REQUEST_QUEUE_PREFIX + methodName;
                String group = GROUP_PREFIX + ":" + methodName;

                ensureConsumerGroup(streamKey, group);
                log.info("Listening on stream: {} with group: {}", streamKey, group);

                Future<?> future = executor.submit(() -> pollStream(streamKey, handler, group));
                methodThreads.put(methodName, future);
            }
        }
    }

    private void scanAndRegisterSupplier(Object supplier) {
        Class<?> supplierClass = supplier.getClass();

        for (Method method : supplierClass.getDeclaredMethods()) {
            Supply supplyAnnotation = method.getAnnotation(Supply.class);

            if (supplyAnnotation != null) {
                String methodName = supplyAnnotation.value();

                if (method.getParameterCount() != 1) {
                    throw new IllegalStateException(
                        "Method " + method.getName() + " annotated with @Supply must have exactly one parameter"
                    );
                }

                Class<?> parameterType = method.getParameterTypes()[0];
                method.setAccessible(true);

                methodHandlers.put(methodName, new MethodHandler(supplier, method, parameterType));
                log.debug("Registered supplier method: {}", methodName);
            }
        }
    }

    /**
     * Stops the server and shuts down all worker threads.
     * Gracefully terminates the executor service with a timeout.
     * This method is idempotent - repeated calls have no effect if already stopped.
     */
    @Override
    public void stop() {
        if (running.compareAndSet(true, false)) {
            log.info("Stopping AnyCall server");
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
     * @param group the consumer group name
     */
    private void ensureConsumerGroup(String streamKey, String group) {
        try {
            commands.xgroupCreate(XReadArgs.StreamOffset.latest(streamKey), group);
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
     * @param group the consumer group name
     */
    private void pollStream(String streamKey, MethodHandler handler, String group) {
        String consumerId = group + "-" + UUID.randomUUID();
        while (running.get()) {
            try {
                List<Object> records = readGroupStream(streamKey, group, consumerId, POLL_BLOCK_TIMEOUT);

                if (records != null && records.size() >= 2) {
                    String messageId = (String) records.get(0);
                    Map<String, String> data = (Map<String, String>) records.get(1);
                    String requestJson = data.get(DATA_FIELD);

                    if (requestJson != null) {
                        processRequest(requestJson, handler);
                        commands.xack(streamKey, group, messageId);
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
            AnyCallRequest request = OBJECT_MAPPER.readValue(requestJson, AnyCallRequest.class);
            requestId = request.requestId();
            methodName = request.methodName();

            if (metricsEnabled) {
                log.debug("[METRICS] [SERVER] [{}] Request deserialized in {}ms", requestId,
                    System.currentTimeMillis() - beforeDeserialize);
            } else {
                log.debug("Processing request: {} for method: {}", requestId, methodName);
            }

            long beforePayloadDeserialize = metricsEnabled ? System.currentTimeMillis() : 0;
            Object parameter = OBJECT_MAPPER.readValue(request.payload(), handler.parameterType());

            if (metricsEnabled) {
                log.debug("[METRICS] [SERVER] [{}] Payload deserialized in {}ms", requestId,
                    System.currentTimeMillis() - beforePayloadDeserialize);
            }

            long beforeInvoke = metricsEnabled ? System.currentTimeMillis() : 0;
            Object result = handler.method().invoke(handler.bean(), parameter);

            if (metricsEnabled) {
                log.debug("[METRICS] [SERVER] [{}] Method '{}' executed in {}ms", requestId, methodName,
                    System.currentTimeMillis() - beforeInvoke);
            }

            long beforeSerialize = metricsEnabled ? System.currentTimeMillis() : 0;
            String resultJson = OBJECT_MAPPER.writeValueAsString(result);

            if (metricsEnabled) {
                log.debug("[METRICS] [SERVER] [{}] Result serialized in {}ms", requestId,
                    System.currentTimeMillis() - beforeSerialize);
            }

            long beforeSend = metricsEnabled ? System.currentTimeMillis() : 0;
            AnyCallResponse response = AnyCallResponse.success(requestId, resultJson);
            sendResponse(response);

            if (metricsEnabled) {
                log.debug("[METRICS] [SERVER] [{}] Response sent in {}ms", requestId,
                    System.currentTimeMillis() - beforeSend);
                log.debug("[METRICS] [SERVER] [{}] Total processing time: {}ms", requestId,
                    System.currentTimeMillis() - startTime);
            } else {
                log.debug("Request {} processed successfully", requestId);
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
            String responseJson = OBJECT_MAPPER.writeValueAsString(response);
            commands.xadd(responseStream, Collections.singletonMap(DATA_FIELD, responseJson));
        } catch (Exception e) {
            log.error("Error sending response: {}", response.requestId(), e);
        }
    }

    private List<Object> readGroupStream(String streamKey, String group, String consumer, Duration timeout) {
        try {
            Consumer<String> consumerRef = Consumer.from(group, consumer);
            XReadArgs args = new XReadArgs();
            args.block(timeout);
            XReadArgs.StreamOffset<String> offset = XReadArgs.StreamOffset.lastConsumed(streamKey);
            List<io.lettuce.core.StreamMessage<String, String>> result = commands.xreadgroup(consumerRef, args, offset);

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
