package dev.kaiquebt.anycall.publisher;

import java.time.Duration;

/**
 * The Redis keys AnyCall uses, all under one prefix ({@value #DEFAULT_PREFIX} unless set at
 * creation), and the timings every implementation shares. Clients and servers find each other
 * only under the same prefix.
 */
public final class AnycallQueues {

    /** The prefix of every key unless another is given at creation. */
    public static final String DEFAULT_PREFIX = "anycall";

    /** The keys under {@value #DEFAULT_PREFIX}. */
    public static final AnycallQueues DEFAULT = new AnycallQueues(DEFAULT_PREFIX);

    private final String prefix;

    /**
     * @param prefix the first part of every key: {@code <prefix>:requests:<method>} and so on
     * @throws IllegalArgumentException if it's null or blank
     */
    public AnycallQueues(String prefix) {
        if (prefix == null || prefix.isBlank()) {
            throw new IllegalArgumentException("prefix must not be null or blank; got " + (prefix == null ? null : "'" + prefix + "'"));
        }
        this.prefix = prefix;
    }

    public String prefix() {
        return prefix;
    }

    /** A method's request queue: {@code <prefix>:requests:<method>}. */
    public String requestQueue(String methodName) {
        return prefix + ":requests:" + methodName;
    }

    /**
     * The response queue of a client, {@code <prefix>:responses:<client id>}: every response
     * to its calls goes there, and the client hands each to its call by request id.
     */
    public String responseQueue(String clientId) {
        return prefix + ":responses:" + clientId;
    }

    /**
     * A server's processing list, {@code <prefix>:processing:<server id>}.
     * <p>
     * One List per server, holding the requests it is processing. A server moves a request
     * here from its method's queue with one {@code BLMOVE} (or {@code BRPOPLPUSH}), so a
     * request is always in its queue or in exactly one of these: the key name is the record
     * of who has it. The server removes it once the response is written; whoever finds the
     * server dead fails back whatever is left (see {@link AnycallReaping}).
     */
    public String processingList(String serverId) {
        return prefix + ":processing:" + serverId;
    }

    /**
     * Sorted set of server ids heartbeating, {@code <prefix>:servers:alive}, scored by Redis's
     * own {@code TIME}. Written by {@link dev.kaiquebt.anycall.server.AnyCallServerImpl}, read
     * by reapers to find dead servers. Members are never pruned by age alone: a dead server leaves only when it is reaped (see
     * {@link AnycallReaping}), so its entry is how its processing list gets found.
     */
    public String heartbeatKey() {
        return prefix + ":servers:alive";
    }

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

    /**
     * Expiry on a tombstone: the string a dead server's processing list becomes once
     * reaping has emptied it (see {@link AnycallReaping}). While it's there, a take that
     * would land on that list fails with {@code WRONGTYPE} and leaves the request in its
     * queue. A server that comes back drains and deletes its own tombstone; this only bounds
     * how long a crashed server's stays.
     */
    public static final Duration TOMBSTONE_TTL = Duration.ofDays(30);
}
