package kaiquebt.dev.anycall.publisher;

/**
 * Constants for Redis stream queue names used by AnyCall.
 * Defines the prefixes for request and response streams.
 */
public class AnycallQueues {

    /**
     * Prefix for request streams. Method name is appended to create the full stream key.
     * Format: {@code anycall:requests:<method-name>}
     */
    public static String REQUEST_QUEUE_PREFIX = "anycall:requests:";

    /**
     * Prefix for response streams. Request ID is appended to create the full stream key.
     * Format: {@code anycall:responses:<request-id>}
     */
    public static String RESPONSE_QUEUE_PREFIX = "anycall:responses:";
}
