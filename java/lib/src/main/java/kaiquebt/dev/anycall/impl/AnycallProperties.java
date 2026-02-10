package kaiquebt.dev.anycall.impl;

import org.springframework.boot.context.properties.ConfigurationProperties;

import java.time.Duration;

/**
 * Configuration properties for AnyCall.
 */
@ConfigurationProperties(prefix = "anycall")
public record AnycallProperties(
    Duration timeout
) {
    public AnycallProperties {
        // Default timeout of 30 seconds if not specified
        if (timeout == null) {
            timeout = Duration.ofSeconds(30);
        }
    }

    public AnycallProperties() {
        this(Duration.ofSeconds(30));
    }
}
