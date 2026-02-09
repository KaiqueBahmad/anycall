package kaiquebt.dev.anycall;

import com.fasterxml.jackson.databind.ObjectMapper;
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
 * Server that processes remote procedure calls from Redis.
 */
public class AnyCallServer {

    private static final Logger log = LoggerFactory.getLogger(AnyCallServer.class);
    private static final String REQUEST_QUEUE_PREFIX = "anycall:requests:";
    private static final String RESPONSE_QUEUE_PREFIX = "anycall:responses:";

    private final StringRedisTemplate redisTemplate;
    private final ObjectMapper objectMapper;
    private final String group;
    private final Map<String, MethodHandler> methodHandlers;
    private final ExecutorService executorService;
    private final AtomicBoolean running;

    public AnyCallServer(
        StringRedisTemplate redisTemplate,
        ObjectMapper objectMapper,
        String group,
        Map<String, MethodHandler> methodHandlers
    ) {
        this.redisTemplate = redisTemplate;
        this.objectMapper = objectMapper;
        this.group = group;
        this.methodHandlers = new HashMap<>(methodHandlers);
        this.executorService = Executors.newFixedThreadPool(methodHandlers.size());
        this.running = new AtomicBoolean(false);
    }

    /**
     * Starts the server and begins processing requests.
     */
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

    /**
     * Stops the server and shuts down all workers.
     */
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

    private void processRequests(String methodName, MethodHandler handler) {
        String requestQueue = REQUEST_QUEUE_PREFIX + methodName;
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
        String requestId = null;
        try {
            // Deserialize the request
            AnyCallRequest request = objectMapper.readValue(requestJson, AnyCallRequest.class);
            requestId = request.requestId();

            log.debug("Processing request: {} for method: {}", requestId, request.methodName());

            // Deserialize the payload
            Object parameter = objectMapper.readValue(request.payload(), handler.parameterType());

            // Invoke the method
            Object result = handler.method().invoke(handler.bean(), parameter);

            // Serialize the result
            String resultJson = objectMapper.writeValueAsString(result);

            // Send the response
            AnyCallResponse response = AnyCallResponse.success(requestId, resultJson);
            sendResponse(response);

            log.debug("Request {} processed successfully", requestId);

        } catch (Exception e) {
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
            String responseQueue = RESPONSE_QUEUE_PREFIX + response.requestId();
            String responseJson = objectMapper.writeValueAsString(response);
            redisTemplate.opsForList().rightPush(responseQueue, responseJson);

            // Set expiration on the response queue (1 minute)
            redisTemplate.expire(responseQueue, 1, TimeUnit.MINUTES);

        } catch (Exception e) {
            log.error("Error sending response: {}", response.requestId(), e);
        }
    }

    public boolean isRunning() {
        return running.get();
    }
}
