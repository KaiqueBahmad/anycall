package dev.kaiquebt.anycall.core;

/**
 * A server's settings, passed to {@link AnyCall#server(String, ServerOptions)}.
 *
 * <pre>{@code
 * AnyCallServer server = AnyCall.server(uri, ServerOptions.DEFAULT.withMaxConcurrency(16));
 * }</pre>
 *
 * Immutable: every {@code with} returns a copy. Invalid values are rejected when the options
 * are made.
 */
public final class ServerOptions {

    /** Options that set nothing: no server-wide concurrency limit. */
    public static final ServerOptions DEFAULT = new ServerOptions(null);

    private final Integer maxConcurrency;

    private ServerOptions(Integer maxConcurrency) {
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
        return new ServerOptions(maxConcurrency);
    }

    /** No server-wide cap: only each method's own {@code @Supply(maxConcurrency)} applies. */
    public ServerOptions withNoConcurrencyLimit() {
        return new ServerOptions(null);
    }

    /** @return the server-wide cap, or {@code null} for none */
    public Integer maxConcurrency() {
        return maxConcurrency;
    }

    @Override
    public String toString() {
        return "ServerOptions{maxConcurrency=" + (maxConcurrency == null ? "none" : maxConcurrency) + "}";
    }
}
