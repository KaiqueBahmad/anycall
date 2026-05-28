package kaiquebt.dev.anycall.impl;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import kaiquebt.dev.anycall.AnyCallException;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.data.redis.connection.stream.StreamRecords;
import org.springframework.data.redis.core.StringRedisTemplate;

import java.util.Collections;

public class AnyCallPublisherImpl implements AnyCallPublisher {

    private static final Logger log = LoggerFactory.getLogger(AnyCallPublisherImpl.class);
    private static final String DATA_FIELD = "data";

    private final StringRedisTemplate redisTemplate;
    private final ObjectMapper objectMapper;

    public AnyCallPublisherImpl(StringRedisTemplate redisTemplate, ObjectMapper objectMapper) {
        this.redisTemplate = redisTemplate;
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
            redisTemplate.opsForStream().add(
                StreamRecords.newRecord().in(stream).ofMap(Collections.singletonMap(DATA_FIELD, message))
            );
            log.debug("Published message to stream: {}", stream);
        } catch (Exception e) {
            throw new AnyCallException("Failed to publish message to stream: " + stream, e);
        }
    }
}
