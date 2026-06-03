package kaiquebt.dev.anycall.core;

import com.fasterxml.jackson.databind.ObjectMapper;
import kaiquebt.dev.anycall.server.AnyCallServerBuilder;

public class AnyCall {

    private AnyCall() {
    }

    public static AnyCallServerBuilder server(RedisStreamAdapter redis) {
        return server(redis, new ObjectMapper());
    }

    public static AnyCallServerBuilder server(RedisStreamAdapter redis, ObjectMapper objectMapper) {
        return new AnyCallServerBuilder(redis, objectMapper);
    }
}
