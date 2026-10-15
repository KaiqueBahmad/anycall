package dev.kaiquebt.anycall.publisher;

import java.time.Duration;

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

    /**
     * Sorted set of server ids heartbeating, scored by Redis's own {@code TIME}. Written by
     * {@link dev.kaiquebt.anycall.server.AnyCallServerImpl}, read by clients to tell whether
     * any server is currently alive before publishing a request.
     */
    public static final String HEARTBEAT_KEY = "anycall:servers:alive";

    /**
     * How long a heartbeat entry is considered live. Must match the TTL argument the server
     * passes into the heartbeat script, or a client's liveness check will disagree with the
     * server's own pruning.
     */
    public static final Duration HEARTBEAT_TTL = Duration.ofSeconds(8);
}
