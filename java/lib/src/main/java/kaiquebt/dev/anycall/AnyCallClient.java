package kaiquebt.dev.anycall;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.data.redis.core.StringRedisTemplate;

import java.time.Duration;
import java.util.concurrent.TimeUnit;

/**
 * Client for making remote procedure calls via Redis.
 */
public class AnyCallClient {

    private static final String REQUEST_QUEUE_PREFIX = "anycall:requests:";
    private static final String RESPONSE_QUEUE_PREFIX = "anycall:responses:";
    private static final Duration DEFAULT_TIMEOUT = Duration.ofSeconds(30);

    private final StringRedisTemplate redisTemplate;
    private final ObjectMapper objectMapper;
    private final Duration timeout;

    public AnyCallClient(StringRedisTemplate redisTemplate, ObjectMapper objectMapper) {
        this(redisTemplate, objectMapper, DEFAULT_TIMEOUT);
    }

    public AnyCallClient(StringRedisTemplate redisTemplate, ObjectMapper objectMapper, Duration timeout) {
        this.redisTemplate = redisTemplate;
        this.objectMapper = objectMapper;
        this.timeout = timeout;
    }

    /**
     * Makes a synchronous call to a remote method.
     *
     * @param methodName the name of the method to call
     * @param request the request payload
     * @param responseType the expected response type
     * @param <T> the type of the response
     * @return the response from the remote method
     * @throws AnyCallException if the call fails or times out
     */
    public <T> T call(String methodName, Object request, Class<T> responseType) {
        try {
            // Serialize the request payload
            String payload = objectMapper.writeValueAsString(request);

            // Create the request
            AnyCallRequest anyCallRequest = AnyCallRequest.create(methodName, payload);
            String requestJson = objectMapper.writeValueAsString(anyCallRequest);

            // Push to the request queue
            String requestQueue = REQUEST_QUEUE_PREFIX + methodName;
            redisTemplate.opsForList().rightPush(requestQueue, requestJson);

            // Wait for response
            String responseQueue = RESPONSE_QUEUE_PREFIX + anyCallRequest.requestId();
            String responseJson = redisTemplate.opsForList().leftPop(
                responseQueue,
                timeout.getSeconds(),
                TimeUnit.SECONDS
            );

            if (responseJson == null) {
                throw new AnyCallException("Timeout waiting for response from method: " + methodName);
            }

            // Deserialize response
            AnyCallResponse response = objectMapper.readValue(responseJson, AnyCallResponse.class);

            if (response.hasError()) {
                throw new AnyCallException("Error from remote method: " + response.error());
            }

            // Deserialize the payload
            return objectMapper.readValue(response.payload(), responseType);

        } catch (Exception e) {
            if (e instanceof AnyCallException) {
                throw (AnyCallException) e;
            }
            throw new AnyCallException("Failed to call method: " + methodName, e);
        }
    }
}
