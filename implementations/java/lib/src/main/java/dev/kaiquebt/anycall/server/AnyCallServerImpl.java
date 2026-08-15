package dev.kaiquebt.anycall.server;

import com.fasterxml.jackson.databind.ObjectMapper;
import dev.kaiquebt.anycall.annotation.Supply;
import dev.kaiquebt.anycall.core.AnyCallServer;
import dev.kaiquebt.anycall.core.AnycallContext;
import dev.kaiquebt.anycall.model.AnyCallRequest;
import dev.kaiquebt.anycall.model.AnyCallResponse;
import dev.kaiquebt.anycall.publisher.AnycallQueues;
import io.lettuce.core.Consumer;
import io.lettuce.core.RedisClient;
import io.lettuce.core.SetArgs;
import io.lettuce.core.StreamMessage;
import io.lettuce.core.XGroupCreateArgs;
import io.lettuce.core.XReadArgs;
import io.lettuce.core.api.StatefulRedisConnection;
import io.lettuce.core.api.sync.RedisCommands;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.lang.reflect.Method;
import java.time.Duration;
import java.util.Collections;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Semaphore;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;

/**
 * Internal implementation of AnyCallServer.
 * <p>
 * <strong>This class is not intended for direct use. Use {@link dev.kaiquebt.anycall.core.AnyCall#server(String)} instead.</strong>
 * </p>
 * One read loop listens on every registered method's stream via a single blocking
 * {@code XREADGROUP} and dispatches to a shared worker pool. The whole server uses
 * exactly two Redis connections — one for reading, one shared for writes — no matter
 * how many methods or how much concurrency is configured.
 */
public class AnyCallServerImpl implements AnyCallServer {

    private static final Logger log = LoggerFactory.getLogger(AnyCallServerImpl.class);
    private static final String DATA_FIELD = "data";
    private static final String GROUP_NAME = "anycall-workers";
    private static final Duration POLL_BLOCK_TIMEOUT = Duration.ofSeconds(5);
    private static final Duration IDLE_POLL_INTERVAL = Duration.ofSeconds(1);
    private static final String HEARTBEAT_KEY_PREFIX = "anycall:heartbeat:";
    private static final Duration HEARTBEAT_INTERVAL = Duration.ofSeconds(5);
    private static final Duration HEARTBEAT_TTL = HEARTBEAT_INTERVAL.multipliedBy(3);
    private static final ObjectMapper OBJECT_MAPPER = new ObjectMapper();

    private final RedisClient redisClient;
    private final StatefulRedisConnection<String, String> readConnection;
    private final RedisCommands<String, String> readCommands;
    private final StatefulRedisConnection<String, String> writeConnection;
    private final RedisCommands<String, String> writeCommands;

    private final Map<String, MethodHandler> methodHandlers;
    private final Map<String, Semaphore> methodConcurrencyLimiters;
    private final Set<String> groupEnsuredStreams;
    private final AtomicBoolean running;
    private final boolean metricsEnabled;
    private final Semaphore globalConcurrencyLimiter;
    private final String serverId;
    private final String heartbeatKey;
    private ExecutorService executor;

    public AnyCallServerImpl(String redisUri, boolean metricsEnabled) {
        this(redisUri, metricsEnabled, null);
    }

    /**
     * @param maxConcurrency server-wide cap on how many requests may be processed at
     *                       the same time, across every registered method combined
     *                       (see {@link dev.kaiquebt.anycall.annotation.Supply#maxConcurrency()});
     *                       {@code null} means uncapped — the sum of each method's own
     *                       {@code maxConcurrency} applies instead
     */
    public AnyCallServerImpl(String redisUri, boolean metricsEnabled, Integer maxConcurrency) {
        if (redisUri == null || redisUri.isEmpty()) {
            throw new IllegalArgumentException("AnyCall Server: redisUri must not be null or blank");
        }
        if (maxConcurrency != null && maxConcurrency < 1) {
            throw new IllegalArgumentException("AnyCall Server: maxConcurrency must be at least 1");
        }
        this.redisClient = RedisClient.create(redisUri);
        this.readConnection = redisClient.connect();
        this.readCommands = readConnection.sync();
        this.writeConnection = redisClient.connect();
        this.writeCommands = writeConnection.sync();
        this.methodHandlers = new ConcurrentHashMap<>();
        this.methodConcurrencyLimiters = new ConcurrentHashMap<>();
        this.groupEnsuredStreams = ConcurrentHashMap.newKeySet();
        this.running = new AtomicBoolean(false);
        this.metricsEnabled = metricsEnabled;
        this.globalConcurrencyLimiter = maxConcurrency != null ? new Semaphore(maxConcurrency) : null;
        this.serverId = "server-" + UUID.randomUUID();
        this.heartbeatKey = HEARTBEAT_KEY_PREFIX + GROUP_NAME + ":" + serverId;
    }

    /**
     * Starts the server and begins processing incoming requests from Redis streams.
     * Spawns the single read loop plus the worker pool that processes dispatched
     * requests. This method is idempotent - repeated calls have no effect if already
     * running.
     *
     * @return this server instance for method chaining
     */
    @Override
    public AnyCallServer start() {
        if (running.compareAndSet(false, true)) {
            log.info("Starting AnyCall server");
            executor = Executors.newCachedThreadPool();
            executor.submit(this::pollAllStreams);
        }
        return this;
    }

    public AnyCallServer register(Object supplier) {
        scanAndRegisterSupplier(supplier);
        return this;
    }

    public AnyCallServer register(Object... suppliers) {
        for (Object supplier : suppliers) {
            scanAndRegisterSupplier(supplier);
        }
        return this;
    }

    /**
     * Unregisters a method. Takes effect on the read loop's next iteration — there's
     * no per-method thread or connection to tear down anymore, since the whole server
     * shares one reader and one writer connection.
     */
    public AnyCallServer unregister(String methodName) {
        MethodHandler removed = methodHandlers.remove(methodName);
        if (removed != null) {
            methodConcurrencyLimiters.remove(methodName);
            log.info("Unregistered method: {}", methodName);
        }
        return this;
    }

    private void scanAndRegisterSupplier(Object supplier) {
        Class<?> supplierClass = supplier.getClass();

        for (Method method : supplierClass.getDeclaredMethods()) {
            Supply supplyAnnotation = method.getAnnotation(Supply.class);

            if (supplyAnnotation != null) {
                String methodName = supplyAnnotation.methodName();

                if (method.getParameterCount() != 2) {
                    throw new IllegalStateException(
                        "Method " + method.getName() + " annotated with @Supply must have exactly two parameters: "
                            + "(AnycallContext, <request type>)"
                    );
                }

                if (method.getParameterTypes()[0] != AnycallContext.class) {
                    throw new IllegalStateException(
                        "Method " + method.getName() + " annotated with @Supply must declare AnycallContext "
                            + "as its first parameter"
                    );
                }

                int maxConcurrency = supplyAnnotation.maxConcurrency();
                if (maxConcurrency < 1) {
                    throw new IllegalStateException(
                        "Method " + method.getName() + " annotated with @Supply has invalid maxConcurrency "
                            + maxConcurrency + "; it must be at least 1"
                    );
                }

                Class<?> parameterType = method.getParameterTypes()[1];
                method.setAccessible(true);

                methodHandlers.put(methodName, new MethodHandler(supplier, method, parameterType, maxConcurrency));
                methodConcurrencyLimiters.put(methodName, new Semaphore(maxConcurrency));
                log.debug("Registered supplier method: {} (maxConcurrency={})", methodName, maxConcurrency);
            }
        }
    }

    /**
     * Stops the server and shuts down the read loop and worker pool.
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
     * Creates the group (and the stream itself via {@code MKSTREAM}, since the
     * stream won't exist yet if no client has ever called this method).
     *
     * @param streamKey the Redis stream key to ensure a consumer group for
     * @param group the consumer group name
     * @return {@code true} if the group exists (created now or already present),
     *         {@code false} if creation failed and should be retried later
     */
    private boolean ensureConsumerGroup(String streamKey, String group) {
        try {
            writeCommands.xgroupCreate(XReadArgs.StreamOffset.latest(streamKey), group, XGroupCreateArgs.Builder.mkstream());
            log.info("Created consumer group '{}' for stream: {}", group, streamKey);
            return true;
        } catch (Exception e) {
            String msg = e.getMessage() != null ? e.getMessage() : "";
            if (msg.contains("BUSYGROUP")) {
                log.debug("Consumer group '{}' already exists for stream: {}", group, streamKey);
                return true;
            }
            log.warn("Could not create consumer group for stream {}: {}", streamKey, msg);
            return false;
        }
    }

    /**
     * Single read loop for every registered method's stream, sharing one consumer
     * group name ({@code anycall-workers}) — Redis scopes a group per (stream, name)
     * pair, so reusing the name across streams doesn't couple the methods together.
     * Reads one message at a time and dispatches without blocking (see
     * {@link #handleMessage}), so a saturated method only piles up its own worker
     * threads waiting on its semaphore, never stalls this loop. Bound that pileup with
     * client-side {@code maxQueueDepth} if it's a concern for a given method.
     */
    private void pollAllStreams() {
        long lastHeartbeat = 0;
        try {
            while (running.get()) {
                try {
                    long now = System.currentTimeMillis();
                    if (now - lastHeartbeat >= HEARTBEAT_INTERVAL.toMillis()) {
                        writeCommands.set(heartbeatKey, String.valueOf(now), SetArgs.Builder.ex(HEARTBEAT_TTL.getSeconds()));
                        lastHeartbeat = now;
                    }

                    Map<String, MethodHandler> snapshot = new HashMap<>(methodHandlers);
                    if (snapshot.isEmpty()) {
                        Thread.sleep(IDLE_POLL_INTERVAL.toMillis());
                        continue;
                    }

                    ensureGroupsForNewStreams(snapshot.keySet());

                    List<StreamMessage<String, String>> result = readCommands.xreadgroup(
                        Consumer.from(GROUP_NAME, serverId),
                        new XReadArgs().block(POLL_BLOCK_TIMEOUT).count(1),
                        buildOffsets(snapshot.keySet())
                    );

                    if (result == null || result.isEmpty()) {
                        continue;
                    }

                    handleMessage(result.get(0), snapshot);
                } catch (InterruptedException e) {
                    Thread.currentThread().interrupt();
                } catch (Exception e) {
                    if (running.get()) {
                        log.error("Error reading from streams: {}", e.getMessage());
                    }
                }
            }
        } finally {
            try {
                writeCommands.del(heartbeatKey);
            } catch (Exception e) {
                log.debug("Failed to clean up heartbeat key {}: {}", heartbeatKey, e.getMessage());
            }
        }
    }

    private void ensureGroupsForNewStreams(Set<String> methodNames) {
        for (String methodName : methodNames) {
            String streamKey = AnycallQueues.REQUEST_QUEUE_PREFIX + methodName;
            if (!groupEnsuredStreams.contains(streamKey) && ensureConsumerGroup(streamKey, GROUP_NAME)) {
                groupEnsuredStreams.add(streamKey);
            }
        }
    }

    @SuppressWarnings("unchecked")
    private XReadArgs.StreamOffset<String>[] buildOffsets(Set<String> methodNames) {
        XReadArgs.StreamOffset<String>[] offsets = new XReadArgs.StreamOffset[methodNames.size()];
        int i = 0;
        for (String methodName : methodNames) {
            offsets[i++] = XReadArgs.StreamOffset.lastConsumed(AnycallQueues.REQUEST_QUEUE_PREFIX + methodName);
        }
        return offsets;
    }

    /**
     * Routes one message to its handler and dispatches to the shared worker pool.
     * Dispatch itself never blocks — the method's {@code maxConcurrency} and the
     * server-wide cap, if any, are acquired inside the submitted task instead.
     *
     * @param msg the message read from one of the request streams
     * @param snapshot the method registry as it was when this message was read
     */
    private void handleMessage(StreamMessage<String, String> msg, Map<String, MethodHandler> snapshot) {
        String streamKey = msg.getStream();
        String messageId = msg.getId();
        String methodName = streamKey.substring(AnycallQueues.REQUEST_QUEUE_PREFIX.length());
        MethodHandler handler = snapshot.get(methodName);

        // TODO verify if this is really the expected behaviour
        if (handler == null) {
            // Unregistered between being read and being routed; nothing left to hand it to.
            log.warn("No handler registered for method '{}'; dropping message {} from stream {}",
                    methodName, messageId, streamKey);
            writeCommands.xack(streamKey, GROUP_NAME, messageId);
            writeCommands.xdel(streamKey, messageId);
            return;
        }

        String requestJson = msg.getBody() != null ? msg.getBody().get(DATA_FIELD) : null;
        if (requestJson == null) {
            log.warn("Discarding malformed message {} on stream {}: missing '{}' field", messageId, streamKey, DATA_FIELD);
            writeCommands.xack(streamKey, GROUP_NAME, messageId);
            writeCommands.xdel(streamKey, messageId);
            return;
        }

        Semaphore methodLimiter = methodConcurrencyLimiters.get(methodName);
        executor.submit(() -> {
            boolean methodAcquired = false;
            boolean globalAcquired = false;
            try {
                try {
                    if (methodLimiter != null) {
                        methodLimiter.acquire();
                        methodAcquired = true;
                    }
                    if (globalConcurrencyLimiter != null) {
                        globalConcurrencyLimiter.acquire();
                        globalAcquired = true;
                    }
                } catch (InterruptedException e) {
                    Thread.currentThread().interrupt();
                    // Never got to run the handler; leave the message unacked in the PEL
                    // rather than pretend it was handled.
                    return;
                }

                processRequest(requestJson, handler);

                writeCommands.xack(streamKey, GROUP_NAME, messageId);
                writeCommands.xdel(streamKey, messageId);
            } finally {
                if (globalAcquired) {
                    globalConcurrencyLimiter.release();
                }
                if (methodAcquired) {
                    methodLimiter.release();
                }
            }
        });
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
            AnycallContext ctx = new AnycallContext(requestId, methodName);
            Object result = handler.method().invoke(handler.bean(), ctx, parameter);

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
            writeCommands.xadd(responseStream, Collections.singletonMap(DATA_FIELD, responseJson));
        } catch (Exception e) {
            log.error("Error sending response: {}", response.requestId(), e);
        }
    }
}
