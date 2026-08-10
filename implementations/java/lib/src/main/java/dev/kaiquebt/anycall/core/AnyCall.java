package dev.kaiquebt.anycall.core;

import dev.kaiquebt.anycall.client.AnyCallClientImpl;
import dev.kaiquebt.anycall.server.AnyCallServerImpl;

import java.time.Duration;

public class AnyCall {
    private AnyCall() {
    }

    public static AnyCallClient client(String redisUri) {
        return new AnyCallClientImpl(redisUri, null, false);
    }

    public static AnyCallClient client(String redisUri, Duration timeout) {
        return new AnyCallClientImpl(redisUri, timeout, false);
    }

    public static AnyCallClient client(String redisUri, boolean metricsEnabled) {
        return new AnyCallClientImpl(redisUri, null, metricsEnabled);
    }

    public static AnyCallClient client(String redisUri, Duration timeout, boolean metricsEnabled) {
        return new AnyCallClientImpl(redisUri, timeout, metricsEnabled);
    }

    /**
     * @param defaultMaxQueueDepth default backlog limit applied to every call made by this
     *                             client (see {@link AnyCallClient#call(String, Object, Class, long)});
     *                             {@code null} means unbounded
     */
    public static AnyCallClient client(String redisUri, Duration timeout, boolean metricsEnabled, Long defaultMaxQueueDepth) {
        return new AnyCallClientImpl(redisUri, timeout, metricsEnabled, defaultMaxQueueDepth);
    }

    public static AnyCallServer server(String redisUri) {
        return new AnyCallServerImpl(redisUri, false);
    }

    public static AnyCallServer server(String redisUri, boolean metricsEnabled) {
        return new AnyCallServerImpl(redisUri, metricsEnabled);
    }

    /**
     * @param maxConcurrency server-wide cap on requests processed at the same time,
     *                       across every registered {@code @Supply} method combined
     *                       (see {@link dev.kaiquebt.anycall.annotation.Supply#maxConcurrency()});
     *                       {@code null} means uncapped
     */
    public static AnyCallServer server(String redisUri, boolean metricsEnabled, Integer maxConcurrency) {
        return new AnyCallServerImpl(redisUri, metricsEnabled, maxConcurrency);
    }
}
