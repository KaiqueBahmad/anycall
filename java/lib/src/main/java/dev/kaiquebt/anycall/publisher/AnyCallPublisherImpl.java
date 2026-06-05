package dev.kaiquebt.anycall.publisher;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import dev.kaiquebt.anycall.core.RedisStreamAdapter;
import dev.kaiquebt.anycall.exception.AnyCallException;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.Collections;

public class AnyCallPublisherImpl implements AnyCallPublisher {

    private static final Logger log = LoggerFactory.getLogger(AnyCallPublisherImpl.class);
    private static final String DATA_FIELD = "data";

    private final RedisStreamAdapter redis;
    private final ObjectMapper objectMapper;

    public AnyCallPublisherImpl(RedisStreamAdapter redis, ObjectMapper objectMapper) {
        this.redis = redis;
        this.objectMapper = objectMapper;
    }

    @Override
    public void publish(String stream, Object message) {
        try {
            String jsonMessage = objectMapper.writeValueAsString(message);
            publishString(stream, jsonMessage);
        } catch (JsonProcessingException e) {
            throw new AnyCallException("Failed to serialize message for stream: " + stream, e);
        }
    }

    @Override
    public void publishString(String stream, String message) {
        try {
            redis.add(stream, Collections.singletonMap(DATA_FIELD, message));
            log.debug("Published message to stream: {}", stream);
        } catch (Exception e) {
            throw new AnyCallException("Failed to publish message to stream: " + stream, e);
        }
    }
}
