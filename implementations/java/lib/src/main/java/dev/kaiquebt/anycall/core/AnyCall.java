package dev.kaiquebt.anycall.core;

import dev.kaiquebt.anycall.client.AnyCallClientImpl;
import dev.kaiquebt.anycall.server.AnyCallServerImpl;

public final class AnyCall {
    private AnyCall() {
    }

    /** A client whose calls wait with no limit and are published however full the queue is. */
    public static AnyCallClient client(String redisUrl) {
        return new AnyCallClientImpl(redisUrl, CallOptions.DEFAULT);
    }

    /**
     * @param defaults the settings of every call the client makes; a setting left out means
     *                 no limit, and a call's own {@link CallOptions} replace them
     */
    public static AnyCallClient client(String redisUrl, CallOptions defaults) {
        return new AnyCallClientImpl(redisUrl, defaults);
    }

    /** A server with no server-wide concurrency limit. */
    public static AnyCallServer server(String redisUrl) {
        return new AnyCallServerImpl(redisUrl, null);
    }

    public static AnyCallServer server(String redisUrl, ServerOptions options) {
        return new AnyCallServerImpl(redisUrl, (options == null ? ServerOptions.DEFAULT : options).maxConcurrency());
    }
}
