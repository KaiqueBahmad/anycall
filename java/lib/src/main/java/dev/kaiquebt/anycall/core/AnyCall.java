package dev.kaiquebt.anycall.core;

import dev.kaiquebt.anycall.client.AnyCallClientImpl;
import dev.kaiquebt.anycall.server.AnyCallServerImpl;
import java.time.Duration;

public class AnyCall {

    private AnyCall() {
    }

    public static AnyCallClient client(String redisUri) {
        return new AnyCallClientImpl(redisUri);
    }

    public static AnyCallClient client(String redisUri, Duration timeout) {
        return new AnyCallClientImpl(redisUri, timeout);
    }

    public static AnyCallClient client(String redisUri, Duration timeout, boolean metricsEnabled) {
        return new AnyCallClientImpl(redisUri, timeout, metricsEnabled);
    }

    public static AnyCallServer server(String redisUri) {
        return new AnyCallServerImpl(redisUri);
    }

    public static AnyCallServer server(String redisUri, boolean metricsEnabled) {
        return new AnyCallServerImpl(redisUri, metricsEnabled);
    }
}
