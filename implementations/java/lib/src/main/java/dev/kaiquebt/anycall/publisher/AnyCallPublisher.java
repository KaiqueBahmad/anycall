package dev.kaiquebt.anycall.publisher;

/**
 * Publisher interface for sending messages to Redis queues (Lists).
 * Provides methods for publishing objects (serialized to JSON) and raw strings to Redis queues.
 */
public interface AnyCallPublisher {

    /**
     * Publishes a serialized message to a Redis queue.
     * The message object is serialized to JSON before being published.
     *
     * @param channel the name of the Redis queue to publish to
     * @param message the message object to serialize and publish
     * @throws dev.kaiquebt.anycall.exception.AnyCallException if serialization or publishing fails
     */
    void publish(String channel, Object message);

    /**
     * Publishes a string message to a Redis queue.
     * The message is published as-is without additional serialization.
     *
     * @param channel the name of the Redis queue to publish to
     * @param message the string message to publish
     * @throws dev.kaiquebt.anycall.exception.AnyCallException if publishing fails
     */
    void publishString(String channel, String message);
}
