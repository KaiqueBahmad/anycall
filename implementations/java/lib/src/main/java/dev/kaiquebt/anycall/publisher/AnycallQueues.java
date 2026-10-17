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
     * Prefix for wake channels. Method name is appended to create the full channel name.
     * Format: {@code anycall:wake:<method-name>}
     * <p>
     * A client publishes here right after pushing a request, so idle servers for that
     * method go look at the queue instead of waiting out their fallback poll. Carries no
     * data — it only means "there may be something new".
     */
    public static final String WAKE_CHANNEL_PREFIX = "anycall:wake:";

    /**
     * Hash of request id → id of the server processing it. A server writes the entry in
     * the same script that pops the request, and removes it once the response is sent;
     * entries whose owner stopped heartbeating are failed back to their client by
     * whichever live server notices first.
     */
    public static final String INFLIGHT_KEY = "anycall:inflight";

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

    /**
     * Expiry on the error response written for a request whose server died: its client
     * may have timed out already, and nothing else would ever delete it.
     */
    public static final Duration ORPHAN_RESPONSE_TTL = Duration.ofSeconds(60);
}
