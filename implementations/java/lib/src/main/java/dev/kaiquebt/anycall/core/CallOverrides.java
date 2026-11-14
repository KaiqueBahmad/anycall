package dev.kaiquebt.anycall.core;

import java.time.Duration;

/**
 * Settings for one call that replace the client's, passed as the last argument of
 * {@code call}, {@code rawCall} and their {@link AsyncCalls} versions. A setting left out
 * keeps the client's.
 *
 * <pre>{@code
 * CallOverrides urgent = CallOverrides.builder()
 *     .timeout(Duration.ofSeconds(5))
 *     .noQueueLimit()
 *     .build();
 * client.call("analyze-sentiment", request, Sentiment.class, urgent);
 * }</pre>
 *
 * Immutable, so the same overrides can be reused across calls. Invalid values are rejected
 * by the builder, when the overrides are made.
 */
public final class CallOverrides {

    /** Overrides that set nothing: every setting is the client's. */
    public static final CallOverrides NONE = new Builder().build();

    private final boolean timeoutSet;
    private final Duration timeout;
    private final boolean maxQueueDepthSet;
    private final Long maxQueueDepth;

    private CallOverrides(Builder builder) {
        this.timeoutSet = builder.timeoutSet;
        this.timeout = builder.timeout;
        this.maxQueueDepthSet = builder.maxQueueDepthSet;
        this.maxQueueDepth = builder.maxQueueDepth;
    }

    public static Builder builder() {
        return new Builder();
    }

    /**
     * The call's timeout: this override's, or {@code clientDefault} if left out.
     *
     * @return the timeout, or {@code null} for no limit
     */
    public Duration timeoutOr(Duration clientDefault) {
        return timeoutSet ? timeout : clientDefault;
    }

    /**
     * The call's queue limit: this override's, or {@code clientDefault} if left out.
     *
     * @return the limit, or {@code null} for no limit
     */
    public Long maxQueueDepthOr(Long clientDefault) {
        return maxQueueDepthSet ? maxQueueDepth : clientDefault;
    }

    @Override
    public String toString() {
        return "CallOverrides{timeout=" + (timeoutSet ? (timeout == null ? "none" : timeout) : "client's")
            + ", maxQueueDepth=" + (maxQueueDepthSet ? (maxQueueDepth == null ? "none" : maxQueueDepth) : "client's")
            + "}";
    }

    /** Builds {@link CallOverrides}; every setting it doesn't set stays the client's. */
    public static final class Builder {
        private boolean timeoutSet;
        private Duration timeout;
        private boolean maxQueueDepthSet;
        private Long maxQueueDepth;

        private Builder() {
        }

        /**
         * How long the call waits for its response.
         *
         * @throws IllegalArgumentException if it isn't positive
         */
        public Builder timeout(Duration timeout) {
            if (timeout == null || timeout.isZero() || timeout.isNegative()) {
                throw new IllegalArgumentException(
                    "timeout must be positive, or use noTimeout() for no limit; got " + timeout);
            }
            this.timeoutSet = true;
            this.timeout = timeout;
            return this;
        }

        /** The call waits for its response with no limit. */
        public Builder noTimeout() {
            this.timeoutSet = true;
            this.timeout = null;
            return this;
        }

        /**
         * Reject the call with {@code QueueFullError} if the method's request queue already
         * holds this many requests.
         *
         * @throws IllegalArgumentException if it's below 1
         */
        public Builder maxQueueDepth(long maxQueueDepth) {
            if (maxQueueDepth < 1) {
                throw new IllegalArgumentException(
                    "maxQueueDepth must be at least 1, or use noQueueLimit() for no limit; got " + maxQueueDepth);
            }
            this.maxQueueDepthSet = true;
            this.maxQueueDepth = maxQueueDepth;
            return this;
        }

        /** The call is published however many requests its method's queue holds. */
        public Builder noQueueLimit() {
            this.maxQueueDepthSet = true;
            this.maxQueueDepth = null;
            return this;
        }

        public CallOverrides build() {
            return new CallOverrides(this);
        }
    }
}
