package dev.kaiquebt.anycall.core;

import org.junit.jupiter.api.Test;

import java.time.Duration;

import static org.junit.jupiter.api.Assertions.*;

class CallOptionsTest {

    @Test
    void leftOutSettingsFallBack() {
        assertEquals(Duration.ofSeconds(30), CallOptions.DEFAULT.timeoutOr(Duration.ofSeconds(30)));
        assertEquals(100L, CallOptions.DEFAULT.maxQueueDepthOr(100L));
        assertNull(CallOptions.DEFAULT.maxQueueDepthOr(null));
    }

    @Test
    void setSettingsWin() {
        CallOptions options = CallOptions.DEFAULT
            .withTimeout(Duration.ofSeconds(5))
            .withMaxQueueDepth(10);

        assertEquals(Duration.ofSeconds(5), options.timeoutOr(Duration.ofSeconds(30)));
        assertEquals(10L, options.maxQueueDepthOr(100L));
    }

    @Test
    void noLimitWins() {
        CallOptions options = CallOptions.DEFAULT.withNoTimeout().withNoQueueLimit();

        assertNull(options.timeoutOr(Duration.ofSeconds(30)));
        assertNull(options.maxQueueDepthOr(100L));
    }

    @Test
    void outOfRangeValuesAreRejectedWhenMade() {
        assertThrows(IllegalArgumentException.class, () -> CallOptions.DEFAULT.withMaxQueueDepth(0));
        assertThrows(IllegalArgumentException.class, () -> CallOptions.DEFAULT.withMaxQueueDepth(-1));
        assertThrows(IllegalArgumentException.class, () -> CallOptions.DEFAULT.withTimeout(Duration.ZERO));
        assertThrows(IllegalArgumentException.class, () -> CallOptions.DEFAULT.withTimeout(Duration.ofSeconds(-1)));
        assertThrows(IllegalArgumentException.class, () -> CallOptions.DEFAULT.withTimeout(null));
    }

    @Test
    void withReturnsACopy() {
        CallOptions limited = CallOptions.DEFAULT.withMaxQueueDepth(10);
        CallOptions both = limited.withTimeout(Duration.ofSeconds(5));

        assertNull(CallOptions.DEFAULT.maxQueueDepthOr(null));
        assertNull(limited.timeoutOr(null));
        assertEquals(10L, both.maxQueueDepthOr(null));
        assertEquals(Duration.ofSeconds(5), both.timeoutOr(null));
    }

    @Test
    void serverOptions() {
        assertNull(ServerOptions.DEFAULT.maxConcurrencyOr(null));
        assertEquals(8, ServerOptions.DEFAULT.maxConcurrencyOr(8));
        assertEquals(16, ServerOptions.DEFAULT.withMaxConcurrency(16).maxConcurrencyOr(null));
        assertNull(ServerOptions.DEFAULT.withMaxConcurrency(16).withNoConcurrencyLimit().maxConcurrencyOr(8));
        assertThrows(IllegalArgumentException.class, () -> ServerOptions.DEFAULT.withMaxConcurrency(0));
    }
}
