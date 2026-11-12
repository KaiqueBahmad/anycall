package dev.kaiquebt.anycall.core;

import dev.kaiquebt.anycall.client.AnyCallClientImpl;
import dev.kaiquebt.anycall.server.AnyCallServerImpl;

import java.time.Duration;

public class AnyCall {
    private AnyCall() {
    }

    public static AnyCallClient client(String redisUri) {
        return new AnyCallClientImpl(redisUri, null);
    }

    public static AnyCallClient client(String redisUri, Duration timeout) {
        return new AnyCallClientImpl(redisUri, timeout);
    }

    /**
     * @param defaultMaxQueueDepth default backlog limit applied to every call made by this
     *                             client (see {@link AnyCallClient#call(String, Object, Class, long)});
     *                             {@code null} means unbounded
     */
    public static AnyCallClient client(String redisUri, Duration timeout, Long defaultMaxQueueDepth) {
        return new AnyCallClientImpl(redisUri, timeout, defaultMaxQueueDepth);
    }

    public static AnyCallServer server(String redisUri) {
        return new AnyCallServerImpl(redisUri);
    }

    /**
     * @param maxConcurrency server-wide cap on requests processed at the same time,
     *                       across every registered {@code @Supply} method combined
     *                       (see {@link dev.kaiquebt.anycall.annotation.Supply#maxConcurrency()});
     *                       {@code null} means uncapped
     */
    public static AnyCallServer server(String redisUri, Integer maxConcurrency) {
        return new AnyCallServerImpl(redisUri, maxConcurrency);
    }
}
