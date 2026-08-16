package dev.kaiquebt.anycall.publisher;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import dev.kaiquebt.anycall.exception.*;
import io.lettuce.core.RedisClient;
import io.lettuce.core.api.StatefulRedisConnection;
import io.lettuce.core.api.sync.RedisCommands;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

/**
 * Internal implementation of AnyCallPublisher.
 * <p>
 * <strong>This class is not intended for direct use.</strong>
 * </p>
 */
public class AnyCallPublisherImpl implements AnyCallPublisher {

    private static final Logger log = LoggerFactory.getLogger(AnyCallPublisherImpl.class);

    private final RedisCommands<String, String> commands;
    private final ObjectMapper objectMapper;

    public AnyCallPublisherImpl(String redisUri, ObjectMapper objectMapper) {
        String actualUri = redisUri != null ? redisUri : "redis://localhost:16379";
        RedisClient client = RedisClient.create(actualUri);
        StatefulRedisConnection<String, String> connection = client.connect();
        this.commands = connection.sync();
        this.objectMapper = objectMapper;
    }

    @Override
    public void publish(String queue, Object message) {
        try {
            String jsonMessage = objectMapper.writeValueAsString(message);
            publishString(queue, jsonMessage);
        } catch (JsonProcessingException e) {
            throw new SerializationError("AnyCall", "Failed to serialize message for queue: " + queue, e);
        }
    }

    @Override
    public void publishString(String queue, String message) {
        try {
            commands.lpush(queue, message);
            log.debug("Published message to queue: {}", queue);
        } catch (Exception e) {
            throw new ConnectionError("AnyCall", "Failed to publish message to queue: " + queue, e);
        }
    }
}
