package kaiquebt.dev.anycall.config;

import java.time.Duration;

public record AnycallProperties(
    Duration timeout,
    Boolean metricsEnabled
) {
    public AnycallProperties {
        if (timeout == null) {
            timeout = Duration.ofSeconds(30);
        }
        if (metricsEnabled == null) {
            metricsEnabled = false;
        }
    }

    public AnycallProperties() {
        this(Duration.ofSeconds(30), false);
    }
}
