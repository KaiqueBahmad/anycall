package dev.kaiquebt.anycall.server;

import com.fasterxml.jackson.databind.ObjectMapper;
import dev.kaiquebt.anycall.annotation.Supply;
import dev.kaiquebt.anycall.core.AnyCallServer;
import dev.kaiquebt.anycall.core.AnycallContext;
import dev.kaiquebt.anycall.model.AnyCallRequest;
import dev.kaiquebt.anycall.model.AnyCallResponse;
import dev.kaiquebt.anycall.publisher.AnycallQueues;
import io.lettuce.core.KeyValue;
import io.lettuce.core.RedisClient;
import io.lettuce.core.api.StatefulRedisConnection;
import io.lettuce.core.api.sync.RedisCommands;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.lang.reflect.Method;
import java.time.Duration;
import java.util.ArrayList;
import java.util.Collections;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
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
 * One read loop listens on every registered method's request queue via a single
 * blocking {@code BRPOP} and dispatches to a shared worker pool. The whole server
 * uses exactly two Redis connections — one for reading and one shared for
 * request/response writes — no matter how many methods or how much concurrency is
 * configured.
 */
public class AnyCallServerImpl implements AnyCallServer {

    private static final Logger log = LoggerFactory.getLogger(AnyCallServerImpl.class);
    private static final Duration POLL_BLOCK_TIMEOUT = Duration.ofSeconds(5);
    private static final Duration IDLE_POLL_INTERVAL = Duration.ofSeconds(1);
    private static final ObjectMapper OBJECT_MAPPER = new ObjectMapper();

    private final RedisClient redisClient;
    private final StatefulRedisConnection<String, String> readConnection;
    private final RedisCommands<String, String> readCommands;
    private final StatefulRedisConnection<String, String> writeConnection;
    private final RedisCommands<String, String> writeCommands;

    private final Map<String, MethodHandler> methodHandlers;
    private final Map<String, Semaphore> methodConcurrencyLimiters;
    private final Set<String> inFlightRequestIds;
    private final AtomicBoolean running;
    private final boolean metricsEnabled;
    private final Semaphore globalConcurrencyLimiter;
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
        this.inFlightRequestIds = ConcurrentHashMap.newKeySet();
        this.running = new AtomicBoolean(false);
        this.metricsEnabled = metricsEnabled;
        this.globalConcurrencyLimiter = maxConcurrency != null ? new Semaphore(maxConcurrency) : null;
    }

    /**
     * Starts the server and begins processing incoming requests from Redis.
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
            executor.submit(this::pollAllQueues);
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
     * Request IDs currently between deserialization and response in {@link #processRequest}.
     * A snapshot, not a live view — safe to iterate without external synchronization.
     */
    public Set<String> getInFlightRequestIds() {
        return Set.copyOf(inFlightRequestIds);
    }

    /**
     * Single read loop for every registered method's request queue. Only blocks on
     * queues with spare {@code maxConcurrency} capacity (see {@link #methodsWithCapacity}),
     * so a saturated method's requests stay in Redis instead of piling up in memory.
     */
    private void pollAllQueues() {
        while (running.get()) {
            try {
                Map<String, MethodHandler> snapshot = new HashMap<>(methodHandlers);
                if (snapshot.isEmpty()) {
                    Thread.sleep(IDLE_POLL_INTERVAL.toMillis());
                    continue;
                }

                Set<String> available = methodsWithCapacity(snapshot.keySet());
                if (available.isEmpty()) {
                    // Every registered method (or the server-wide cap) is fully
                    // saturated right now — back off instead of busy-looping.
                    Thread.sleep(IDLE_POLL_INTERVAL.toMillis());
                    continue;
                }

                KeyValue<String, String> entry = readCommands.brpop(
                    POLL_BLOCK_TIMEOUT.getSeconds(),
                    buildQueueKeys(available)
                );

                if (entry == null) {
                    continue;
                }

                handleMessage(entry, snapshot);
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
            } catch (Exception e) {
                if (running.get()) {
                    log.error("Error reading from queues: {}", e.getMessage());
                }
            }
        }
    }

    // TODO: review whole concurrency implementation
    /**
     * Methods with a free permit on both their own semaphore and the server-wide
     * one, if any. A point-in-time read, not a reservation, so it can be stale by
     * the time {@link #handleMessage} actually acquires — that's fine, worst case
     * one extra request gets popped just as its method fills up.
     */
    private Set<String> methodsWithCapacity(Set<String> methodNames) {
        if (globalConcurrencyLimiter != null && globalConcurrencyLimiter.availablePermits() <= 0) {
            return Set.of();
        }
        Set<String> available = new HashSet<>();
        for (String methodName : methodNames) {
            Semaphore limiter = methodConcurrencyLimiters.get(methodName);
            if (limiter == null || limiter.availablePermits() > 0) {
                available.add(methodName);
            }
        }
        return available;
    }

    /**
     * Builds the array of request queue keys to block on, shuffled so that BRPOP's
     * preference for the first key with data available doesn't starve a method that
     * consistently sorts after a busier one in {@code methodNames}' iteration order.
     */
    private String[] buildQueueKeys(Set<String> methodNames) {
        List<String> keys = new ArrayList<>(methodNames.size());
        for (String methodName : methodNames) {
            keys.add(AnycallQueues.REQUEST_QUEUE_PREFIX + methodName);
        }
        Collections.shuffle(keys);
        return keys.toArray(new String[0]);
    }

    /**
     * Routes one popped request to its handler. Acquires both semaphores on this
     * (the poll loop's) thread, before dispatching — since {@link #methodsWithCapacity}
     * already filtered for availability, this is normally instant; it only actually
     * waits if that pre-filter's read is stale, which is exactly when the loop
     * should wait rather than pop another request the method has no room for.
     *
     * @param entry the queue key and raw request JSON popped by BRPOP
     * @param snapshot the method registry as it was when this entry was read
     */
    private void handleMessage(KeyValue<String, String> entry, Map<String, MethodHandler> snapshot) {
        String queueKey = entry.getKey();
        String requestJson = entry.getValue();
        String methodName = queueKey.substring(AnycallQueues.REQUEST_QUEUE_PREFIX.length());
        MethodHandler handler = snapshot.get(methodName);

        // TODO verify if this is really the expected behaviour
        if (handler == null) {
            // Unregistered between being popped and being routed; nothing left to hand
            // it to. BRPOP already removed it from Redis, so there's nothing to clean up.
            log.warn("No handler registered for method '{}'; dropping request from queue {}",
                    methodName, queueKey);
            return;
        }

        Semaphore methodLimiter = methodConcurrencyLimiters.get(methodName);
        boolean methodAcquired = false;
        boolean globalAcquired = false;
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
            if (methodAcquired) {
                methodLimiter.release();
            }
            // BRPOP already removed this entry from Redis when it was popped, so
            // never getting to run the handler just means it's lost — same
            // at-most-once semantics as before under NOACK.
            return;
        }

        boolean releaseGlobal = globalAcquired;
        boolean releaseMethod = methodAcquired;
        executor.submit(() -> {
            try {
                processRequest(requestJson, handler);
            } finally {
                if (releaseGlobal) {
                    globalConcurrencyLimiter.release();
                }
                if (releaseMethod) {
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
            inFlightRequestIds.add(requestId);

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
        } finally {
            if (requestId != null) {
                inFlightRequestIds.remove(requestId);
            }
        }
    }

    /**
     * Sends a response back to the client via a Redis queue.
     * Serializes the response and pushes it to the client's response queue.
     *
     * @param response the response to send
     */
    private void sendResponse(AnyCallResponse response) {
        try {
            String responseQueue = AnycallQueues.RESPONSE_QUEUE_PREFIX + response.requestId();
            String responseJson = OBJECT_MAPPER.writeValueAsString(response);
            writeCommands.lpush(responseQueue, responseJson);
        } catch (Exception e) {
            log.error("Error sending response: {}", response.requestId(), e);
        }
    }
}
