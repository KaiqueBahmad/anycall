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
     * Prefix for processing lists. Server id is appended to create the full key.
     * Format: {@code anycall:processing:<server-id>}
     * <p>
     * One List per server, holding the requests it is processing. A server moves a request
     * here from its method's queue with one {@code BLMOVE} (or {@code BRPOPLPUSH}), so a request is always in its
     * queue or in exactly one of these: the key name is the record of who has it. The server
     * removes it once the response is written; whoever finds the server dead fails back
     * whatever is left (see {@link AnycallReaping}).
     */
    public static final String PROCESSING_PREFIX = "anycall:processing:";

    /**
     * Sorted set of server ids heartbeating, scored by Redis's own {@code TIME}. Written by
     * {@link dev.kaiquebt.anycall.server.AnyCallServerImpl}, read by clients to tell whether
     * any server is currently alive before publishing a request. Members are never pruned
     * by age alone: a dead server leaves only when it is reaped (see {@link AnycallReaping}),
     * so its entry is how its processing list gets found.
     */
    public static final String HEARTBEAT_KEY = "anycall:servers:alive";

    /**
     * How long a heartbeat entry is considered live. Must match the TTL argument the server
     * passes into the heartbeat script, or a client's liveness check will disagree with the
     * server's own pruning.
     */
    public static final Duration HEARTBEAT_TTL = Duration.ofSeconds(8);

    /**
     * Expiry on every response queue, set when a response is written (see
     * {@link AnycallResponses}). A waiting client pops it within milliseconds and deletes
     * the queue; this only matters when nobody reads it, so it doesn't sit in Redis forever.
     */
    public static final Duration RESPONSE_TTL = Duration.ofSeconds(60);
}
