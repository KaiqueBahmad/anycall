package dev.kaiquebt.anycall.config;

import java.time.Duration;

public record AnycallProperties(
    Duration timeout,
    Boolean metricsEnabled
) {
    public AnycallProperties {
        if (timeout == null) {
            timeout = Duration.ZERO;
        }
        if (metricsEnabled == null) {
            metricsEnabled = false;
        }
    }

    public AnycallProperties() {
        this(Duration.ZERO, false);
    }
}
