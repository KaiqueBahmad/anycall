package dev.kaiquebt.anycall.core;

import org.junit.jupiter.api.Test;

import java.time.Duration;

import static org.junit.jupiter.api.Assertions.*;

class CallOverridesTest {

    @Test
    void leftOutSettingsKeepTheClients() {
        assertEquals(Duration.ofSeconds(30), CallOverrides.NONE.timeoutOr(Duration.ofSeconds(30)));
        assertEquals(100L, CallOverrides.NONE.maxQueueDepthOr(100L));
        assertNull(CallOverrides.NONE.maxQueueDepthOr(null));
    }

    @Test
    void setSettingsReplaceTheClients() {
        CallOverrides overrides = CallOverrides.builder()
            .timeout(Duration.ofSeconds(5))
            .maxQueueDepth(10)
            .build();

        assertEquals(Duration.ofSeconds(5), overrides.timeoutOr(Duration.ofSeconds(30)));
        assertEquals(10L, overrides.maxQueueDepthOr(100L));
    }

    @Test
    void noLimitReplacesTheClientsLimit() {
        CallOverrides overrides = CallOverrides.builder().noTimeout().noQueueLimit().build();

        assertNull(overrides.timeoutOr(Duration.ofSeconds(30)));
        assertNull(overrides.maxQueueDepthOr(100L));
    }

    @Test
    void outOfRangeValuesAreRejectedWhenMade() {
        CallOverrides.Builder builder = CallOverrides.builder();

        assertThrows(IllegalArgumentException.class, () -> builder.maxQueueDepth(0));
        assertThrows(IllegalArgumentException.class, () -> builder.maxQueueDepth(-1));
        assertThrows(IllegalArgumentException.class, () -> builder.timeout(Duration.ZERO));
        assertThrows(IllegalArgumentException.class, () -> builder.timeout(Duration.ofSeconds(-1)));
        assertThrows(IllegalArgumentException.class, () -> builder.timeout(null));
    }

    @Test
    void overridesAreUnchangedByTheBuilderAfterwards() {
        CallOverrides.Builder builder = CallOverrides.builder().maxQueueDepth(10);
        CallOverrides overrides = builder.build();

        builder.maxQueueDepth(20);

        assertEquals(10L, overrides.maxQueueDepthOr(null));
    }
}
