package dev.kaiquebt.anycall.core;

import dev.kaiquebt.anycall.client.AnyCallClientImpl;
import dev.kaiquebt.anycall.publisher.AnyCallQueues;
import dev.kaiquebt.anycall.server.AnyCallServerImpl;

/**
 * Creates clients and servers. Both find each other through the keys under one prefix,
 * {@value AnyCallQueues#DEFAULT_PREFIX} unless another is given; the prefix is fixed for the
 * life of a client or server, while its options can change (see
 * {@link AnyCallClient#updateDefaults} and {@link AnyCallServer#updateOptions}).
 */
public final class AnyCall {
    private AnyCall() {
    }

    /** A client whose calls wait with no limit and are published however full the queue is. */
    public static AnyCallClient client(String redisUrl) {
        return client(redisUrl, AnyCallQueues.DEFAULT_PREFIX, CallOptions.DEFAULT);
    }

    /**
     * @param defaults the settings of every call the client makes; a setting left out means
     *                 no limit, and a call's own {@link CallOptions} replace them
     */
    public static AnyCallClient client(String redisUrl, CallOptions defaults) {
        return client(redisUrl, AnyCallQueues.DEFAULT_PREFIX, defaults);
    }

    /**
     * @param prefix the first part of every key the client uses ({@code <prefix>:requests:...});
     *               a server answers it only under the same prefix
     */
    public static AnyCallClient client(String redisUrl, String prefix) {
        return client(redisUrl, prefix, CallOptions.DEFAULT);
    }

    public static AnyCallClient client(String redisUrl, String prefix, CallOptions defaults) {
        return new AnyCallClientImpl(redisUrl, new AnyCallQueues(prefix), defaults);
    }

    /** A server with no server-wide concurrency limit. */
    public static AnyCallServer server(String redisUrl) {
        return server(redisUrl, AnyCallQueues.DEFAULT_PREFIX, ServerOptions.DEFAULT);
    }

    /** @param options the server's settings; a setting left out means no limit */
    public static AnyCallServer server(String redisUrl, ServerOptions options) {
        return server(redisUrl, AnyCallQueues.DEFAULT_PREFIX, options);
    }

    /**
     * @param prefix the first part of every key the server uses ({@code <prefix>:requests:...});
     *               it serves only clients under the same prefix
     */
    public static AnyCallServer server(String redisUrl, String prefix) {
        return server(redisUrl, prefix, ServerOptions.DEFAULT);
    }

    public static AnyCallServer server(String redisUrl, String prefix, ServerOptions options) {
        return new AnyCallServerImpl(redisUrl, new AnyCallQueues(prefix), options);
    }
}
