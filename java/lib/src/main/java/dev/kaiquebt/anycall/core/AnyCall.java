package dev.kaiquebt.anycall.core;

import com.fasterxml.jackson.databind.ObjectMapper;
import dev.kaiquebt.anycall.server.AnyCallServerBuilder;

public class AnyCall {

    private AnyCall() {
    }

    public static AnyCallServerBuilder server(String redisUri) {
        return server(redisUri, new ObjectMapper());
    }

    public static AnyCallServerBuilder server(String redisUri, ObjectMapper objectMapper) {
        return new AnyCallServerBuilder(redisUri, objectMapper);
    }
}
