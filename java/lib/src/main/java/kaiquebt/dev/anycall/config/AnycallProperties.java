package kaiquebt.dev.anycall.config;

import org.springframework.boot.context.properties.ConfigurationProperties;

import java.time.Duration;

/**
 * Configuration properties for AnyCall.
 */
@ConfigurationProperties(prefix = "anycall")
public record AnycallProperties(
    Duration timeout,
    Boolean metricsEnabled
) {
    public AnycallProperties {
        // Default timeout of 30 seconds if not specified
        if (timeout == null) {
            timeout = Duration.ofSeconds(30);
        }
        // Default metrics disabled
        if (metricsEnabled == null) {
            metricsEnabled = false;
        }
    }

    public AnycallProperties() {
        this(Duration.ofSeconds(30), false);
    }
}
