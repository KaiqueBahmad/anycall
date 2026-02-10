package kaiquebt.dev.anycall.impl;

import com.fasterxml.jackson.databind.ObjectMapper;
import kaiquebt.dev.anycall.AnyCallClient;
import org.springframework.boot.autoconfigure.AutoConfiguration;
import org.springframework.boot.autoconfigure.condition.ConditionalOnClass;
import org.springframework.boot.autoconfigure.condition.ConditionalOnMissingBean;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.ComponentScan;
import org.springframework.data.redis.core.StringRedisTemplate;

/**
 * Auto-configuration for AnyCall.
 * Automatically creates an AnyCallClient bean when Spring Data Redis is available.
 */
@AutoConfiguration
@EnableConfigurationProperties(AnycallProperties.class)
@ComponentScan(basePackages = "kaiquebt.dev.anycall")
@ConditionalOnClass(StringRedisTemplate.class)
public class AnycallAutoConfiguration {

    /**
     * Creates an ObjectMapper bean if one doesn't already exist.
     */
    @Bean
    @ConditionalOnMissingBean
    public ObjectMapper objectMapper() {
        return new ObjectMapper();
    }

    /**
     * Creates an AnyCallClient bean for making remote procedure calls.
     */
    @Bean
    @ConditionalOnMissingBean
    public AnyCallClient anyCallClient(
        StringRedisTemplate redisTemplate,
        ObjectMapper objectMapper,
        AnycallProperties properties
    ) {
        return new AnyCallClientImpl(redisTemplate, objectMapper, properties.timeout());
    }
}
