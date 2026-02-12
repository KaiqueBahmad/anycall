package kaiquebt.dev.anycall.impl;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import kaiquebt.dev.anycall.AnyCallException;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.data.redis.core.StringRedisTemplate;

/**
 * Default implementation of AnyCallPublisher using Redis pub/sub.
 */
public class AnyCallPublisherImpl implements AnyCallPublisher {

    private static final Logger log = LoggerFactory.getLogger(AnyCallPublisherImpl.class);

    private final StringRedisTemplate redisTemplate;
    private final ObjectMapper objectMapper;

    public AnyCallPublisherImpl(StringRedisTemplate redisTemplate, ObjectMapper objectMapper) {
        this.redisTemplate = redisTemplate;
        this.objectMapper = objectMapper;
    }

    @Override
    public void publish(String channel, Object message) {
        try {
            String jsonMessage = objectMapper.writeValueAsString(message);
            publishString(channel, jsonMessage);
        } catch (JsonProcessingException e) {
            throw new AnyCallException("Failed to serialize message for channel: " + channel, e);
        }
    }

    @Override
    public void publishString(String channel, String message) {
        try {
            redisTemplate.convertAndSend(channel, message);
            log.debug("Published message to channel: {}", channel);
        } catch (Exception e) {
            throw new AnyCallException("Failed to publish message to channel: " + channel, e);
        }
    }
}
