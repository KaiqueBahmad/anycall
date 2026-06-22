package dev.kaiquebt.anycall.core;

import dev.kaiquebt.anycall.client.AnyCallClientImpl;
import dev.kaiquebt.anycall.server.AnyCallServerImpl;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.time.Duration;

public class AnyCall {
    private static final Logger log = LoggerFactory.getLogger(AnyCall.class);

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

    public static AnyCallServer server(String redisUri) {
        return new AnyCallServerImpl(redisUri, false);
    }

    public static AnyCallServer server(String redisUri, boolean metricsEnabled) {
        return new AnyCallServerImpl(redisUri, metricsEnabled);
    }
}
