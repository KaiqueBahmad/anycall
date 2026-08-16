package dev.kaiquebt.anycall.publisher;

/**
 * Constants for Redis queue names used by AnyCall.
 * Defines the prefixes for request and response queues.
 */
public class AnycallQueues {

    /**
     * Prefix for request queues. Method name is appended to create the full queue key.
     * Format: {@code anycall:requests:<method-name>}
     */
    public static String REQUEST_QUEUE_PREFIX = "anycall:requests:";

    /**
     * Prefix for response queues. Request ID is appended to create the full queue key.
     * Format: {@code anycall:responses:<request-id>}
     */
    public static String RESPONSE_QUEUE_PREFIX = "anycall:responses:";
}
