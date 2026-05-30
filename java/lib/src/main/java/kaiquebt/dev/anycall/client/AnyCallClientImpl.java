package kaiquebt.dev.anycall.client;

import com.fasterxml.jackson.databind.ObjectMapper;
import kaiquebt.dev.anycall.core.AnyCallClient;
import kaiquebt.dev.anycall.exception.AnyCallException;
import kaiquebt.dev.anycall.model.AnyCallRequest;
import kaiquebt.dev.anycall.model.AnyCallResponse;
import kaiquebt.dev.anycall.publisher.AnycallQueues;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.data.redis.connection.stream.*;
import org.springframework.data.redis.core.StringRedisTemplate;

import java.time.Duration;
import java.util.Collections;
import java.util.List;

public class AnyCallClientImpl implements AnyCallClient {

    private static final Logger log = LoggerFactory.getLogger(AnyCallClientImpl.class);
    private static final Duration DEFAULT_TIMEOUT = Duration.ofSeconds(30);
    private static final String DATA_FIELD = "data";

    private final StringRedisTemplate redisTemplate;
    private final ObjectMapper objectMapper;
    private final Duration timeout;
    private final boolean metricsEnabled;

    public AnyCallClientImpl(StringRedisTemplate redisTemplate, ObjectMapper objectMapper) {
        this(redisTemplate, objectMapper, DEFAULT_TIMEOUT, false);
    }

    public AnyCallClientImpl(StringRedisTemplate redisTemplate, ObjectMapper objectMapper, Duration timeout) {
        this(redisTemplate, objectMapper, timeout, false);
    }

    public AnyCallClientImpl(StringRedisTemplate redisTemplate, ObjectMapper objectMapper, Duration timeout, boolean metricsEnabled) {
        this.redisTemplate = redisTemplate;
        this.objectMapper = objectMapper;
        this.timeout = timeout;
        this.metricsEnabled = metricsEnabled;
    }

    @Override
    @SuppressWarnings("unchecked")
    public <T> T call(String methodName, Object request, Class<T> responseType) {
        long startTime = metricsEnabled ? System.currentTimeMillis() : 0;
        String _requestId = null;
        String responseStream = null;

        try {
            if (metricsEnabled) {
                log.info("[METRICS] [CLIENT] Starting call to method: {}", methodName);
            }

            String payload = objectMapper.writeValueAsString(request);

            AnyCallRequest anyCallRequest = AnyCallRequest.create(methodName, payload);
            String requestId = anyCallRequest.requestId();
            _requestId = requestId;
            String requestJson = objectMapper.writeValueAsString(anyCallRequest);

            if (metricsEnabled) {
                log.info("[METRICS] [CLIENT] [{}] Request serialized in {}ms", requestId,
                    System.currentTimeMillis() - startTime);
            }

            // Publish request to stream
            long beforePush = metricsEnabled ? System.currentTimeMillis() : 0;
            String requestStream = AnycallQueues.REQUEST_QUEUE_PREFIX + methodName;
            redisTemplate.opsForStream().add(
                StreamRecords.newRecord().in(requestStream).ofMap(Collections.singletonMap(DATA_FIELD, requestJson))
            );

            if (metricsEnabled) {
                log.info("[METRICS] [CLIENT] [{}] Request published to stream in {}ms", requestId,
                    System.currentTimeMillis() - beforePush);
            }

            // Block-read the response stream from the beginning (0-0 avoids missing fast responses)
            responseStream = AnycallQueues.RESPONSE_QUEUE_PREFIX + requestId;
            long beforeWait = metricsEnabled ? System.currentTimeMillis() : 0;

            StreamReadOptions readOptions = StreamReadOptions.empty().block(timeout).count(1);
            List<MapRecord<String, Object, Object>> records = redisTemplate.opsForStream()
                .read(readOptions, StreamOffset.create(responseStream, ReadOffset.from("0-0")));

            if (metricsEnabled) {
                log.info("[METRICS] [CLIENT] [{}] Response received after {}ms", requestId,
                    System.currentTimeMillis() - beforeWait);
            }

            if (records == null || records.isEmpty()) {
                throw new AnyCallException("Timeout waiting for response from method: " + methodName);
            }

            // Deserialize response
            long beforeDeserialize = metricsEnabled ? System.currentTimeMillis() : 0;
            String responseJson = (String) records.get(0).getValue().get(DATA_FIELD);
            AnyCallResponse response = objectMapper.readValue(responseJson, AnyCallResponse.class);

            if (response.hasError()) {
                throw new AnyCallException("Error from remote method: " + response.error());
            }

            T result = objectMapper.readValue(response.payload(), responseType);

            if (metricsEnabled) {
                log.info("[METRICS] [CLIENT] [{}] Response deserialized in {}ms", requestId,
                    System.currentTimeMillis() - beforeDeserialize);
                log.info("[METRICS] [CLIENT] [{}] Total call duration: {}ms", requestId,
                    System.currentTimeMillis() - startTime);
            }

            return result;
        } catch (Exception e) {
            if (metricsEnabled && _requestId != null) {
                log.error("[METRICS] [CLIENT] [{}] Call failed after {}ms: {}", _requestId,
                    System.currentTimeMillis() - startTime, e.getMessage());
            }
            if (e instanceof AnyCallException) {
                throw (AnyCallException) e;
            }
            throw new AnyCallException("Failed to call method: " + methodName, e);
        } finally {
            if (responseStream != null) {
                redisTemplate.delete(responseStream);
            }
        }
    }
}
