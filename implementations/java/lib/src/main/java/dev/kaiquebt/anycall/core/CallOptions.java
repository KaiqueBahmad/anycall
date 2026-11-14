package dev.kaiquebt.anycall.core;

import java.time.Duration;

/**
 * A call's settings: its timeout and its queue limit.
 * <p>
 * Passed to {@link AnyCall#client(String, CallOptions)}, they're the defaults of every call
 * the client makes; a setting left out there means no limit. Passed as the last argument of
 * {@code call}, {@code rawCall} and their {@link AsyncCalls} versions, they apply to that one
 * call; a setting left out there keeps the client's.
 *
 * <pre>{@code
 * AnyCallClient client = AnyCall.client(uri,
 *     CallOptions.DEFAULT.withTimeout(Duration.ofSeconds(30)).withMaxQueueDepth(100));
 *
 * client.call("analyze-sentiment", request, Sentiment.class,
 *     CallOptions.DEFAULT.withTimeout(Duration.ofSeconds(5)).withNoQueueLimit());
 * }</pre>
 *
 * Immutable: every {@code with} returns a copy, so the same options can be reused. Invalid
 * values are rejected when the options are made.
 */
public final class CallOptions {

    /** Options that set nothing. */
    public static final CallOptions DEFAULT = new CallOptions(false, null, false, null);

    private final boolean timeoutSet;
    private final Duration timeout;
    private final boolean maxQueueDepthSet;
    private final Long maxQueueDepth;

    private CallOptions(boolean timeoutSet, Duration timeout, boolean maxQueueDepthSet, Long maxQueueDepth) {
        this.timeoutSet = timeoutSet;
        this.timeout = timeout;
        this.maxQueueDepthSet = maxQueueDepthSet;
        this.maxQueueDepth = maxQueueDepth;
    }

    /**
     * How long the call waits for its response.
     *
     * @throws IllegalArgumentException if it isn't positive
     */
    public CallOptions withTimeout(Duration timeout) {
        if (timeout == null || timeout.isZero() || timeout.isNegative()) {
            throw new IllegalArgumentException(
                "timeout must be positive, or use withNoTimeout() for no limit; got " + timeout);
        }
        return new CallOptions(true, timeout, maxQueueDepthSet, maxQueueDepth);
    }

    /** The call waits for its response with no limit. */
    public CallOptions withNoTimeout() {
        return new CallOptions(true, null, maxQueueDepthSet, maxQueueDepth);
    }

    /**
     * Reject the call with {@code QueueFullError} if the method's request queue already holds
     * this many requests.
     *
     * @throws IllegalArgumentException if it's below 1
     */
    public CallOptions withMaxQueueDepth(long maxQueueDepth) {
        if (maxQueueDepth < 1) {
            throw new IllegalArgumentException(
                "maxQueueDepth must be at least 1, or use withNoQueueLimit() for no limit; got " + maxQueueDepth);
        }
        return new CallOptions(timeoutSet, timeout, true, maxQueueDepth);
    }

    /** The call is published however many requests its method's queue holds. */
    public CallOptions withNoQueueLimit() {
        return new CallOptions(timeoutSet, timeout, true, null);
    }

    /**
     * The timeout these options set, or {@code fallback} if they leave it out. Used by the
     * client to settle a call's timeout.
     *
     * @return the timeout, or {@code null} for no limit
     */
    public Duration timeoutOr(Duration fallback) {
        return timeoutSet ? timeout : fallback;
    }

    /**
     * The queue limit these options set, or {@code fallback} if they leave it out. Used by the
     * client to settle a call's queue limit.
     *
     * @return the limit, or {@code null} for no limit
     */
    public Long maxQueueDepthOr(Long fallback) {
        return maxQueueDepthSet ? maxQueueDepth : fallback;
    }

    @Override
    public String toString() {
        return "CallOptions{timeout=" + (timeoutSet ? (timeout == null ? "none" : timeout) : "unset")
            + ", maxQueueDepth=" + (maxQueueDepthSet ? (maxQueueDepth == null ? "none" : maxQueueDepth) : "unset")
            + "}";
    }
}
