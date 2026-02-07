package kaiquebt.dev.anycall;

import org.springframework.boot.context.properties.ConfigurationProperties;
@ConfigurationProperties(prefix = "anycall")
public record AnycallProperties(String foo) {
}
