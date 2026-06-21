package dev.kaiquebt.anycall.test;

import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;
import static org.assertj.core.api.Assertions.*;

public class BasicIntegrationTest {

    private static String redisUri;

    @BeforeAll
    static void setUp() {
        redisUri = System.getenv("REDIS_URI");
        if (redisUri == null) {
            redisUri = "redis://localhost:6379";
        }
    }

    @Test
    void testRedisConnectionAvailable() {
        // Placeholder for Redis connectivity test
        assertThat(redisUri).isNotEmpty();
    }

    @Test
    void testAnyCallClientInitialization() {
        // Placeholder for AnyCall client initialization test
        assertThat(redisUri).startsWith("redis://");
    }
}
