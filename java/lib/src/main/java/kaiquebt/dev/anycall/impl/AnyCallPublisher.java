package kaiquebt.dev.anycall.impl;

/**
 * Publisher for sending messages to Redis channels using pub/sub.
 */
public interface AnyCallPublisher {

    /**
     * Publishes a message to a Redis channel.
     *
     * @param channel the channel name
     * @param message the message to publish
     */
    void publish(String channel, Object message);

    /**
     * Publishes a string message to a Redis channel.
     *
     * @param channel the channel name
     * @param message the string message to publish
     */
    void publishString(String channel, String message);
}
