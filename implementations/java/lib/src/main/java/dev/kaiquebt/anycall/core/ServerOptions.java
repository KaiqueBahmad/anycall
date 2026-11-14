package dev.kaiquebt.anycall.core;

/**
 * A server's settings.
 * <p>
 * Passed to {@link AnyCall#server(String, ServerOptions)}, a setting left out means no limit.
 * Passed to {@link AnyCallServer#updateOptions}, a setting left out stays as the server has it.
 *
 * <pre>{@code
 * AnyCallServer server = AnyCall.server(uri, ServerOptions.DEFAULT.withMaxConcurrency(16));
 * server.updateOptions(ServerOptions.DEFAULT.withMaxConcurrency(32));
 * }</pre>
 *
 * Immutable: every {@code with} returns a copy. Invalid values are rejected when the options
 * are made.
 */
public final class ServerOptions {

    /** Options that set nothing. */
    public static final ServerOptions DEFAULT = new ServerOptions(false, null);

    private final boolean maxConcurrencySet;
    private final Integer maxConcurrency;

    private ServerOptions(boolean maxConcurrencySet, Integer maxConcurrency) {
        this.maxConcurrencySet = maxConcurrencySet;
        this.maxConcurrency = maxConcurrency;
    }

    /**
     * Server-wide cap on requests processed at the same time, across every registered method
     * combined; each method's own {@code @Supply(maxConcurrency)} still applies.
     *
     * @throws IllegalArgumentException if it's below 1
     */
    public ServerOptions withMaxConcurrency(int maxConcurrency) {
        if (maxConcurrency < 1) {
            throw new IllegalArgumentException(
                "maxConcurrency must be at least 1, or use withNoConcurrencyLimit() for no limit; got "
                    + maxConcurrency);
        }
        return new ServerOptions(true, maxConcurrency);
    }

    /** No server-wide cap: only each method's own {@code @Supply(maxConcurrency)} applies. */
    public ServerOptions withNoConcurrencyLimit() {
        return new ServerOptions(true, null);
    }

    /**
     * The server-wide cap these options set, or {@code fallback} if they leave it out. Used by
     * the server to settle its cap.
     *
     * @return the cap, or {@code null} for none
     */
    public Integer maxConcurrencyOr(Integer fallback) {
        return maxConcurrencySet ? maxConcurrency : fallback;
    }

    @Override
    public String toString() {
        return "ServerOptions{maxConcurrency="
            + (maxConcurrencySet ? (maxConcurrency == null ? "none" : maxConcurrency) : "unset") + "}";
    }
}
