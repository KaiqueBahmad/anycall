package kaiquebt.dev.anycall.core;

import com.fasterxml.jackson.databind.ObjectMapper;
import kaiquebt.dev.anycall.server.AnyCallServerBuilder;
import org.springframework.context.ApplicationContext;
import org.springframework.data.redis.core.StringRedisTemplate;

/**
 * Main entry point for creating AnyCall servers.
 */
public class AnyCall {

    private AnyCall() {
        // Utility class
    }

    /**
     * Creates a new server builder using the ApplicationContext to obtain required beans.
     *
     * @param applicationContext the Spring ApplicationContext
     * @return a server builder
     */
    public static AnyCallServerBuilder server(ApplicationContext applicationContext) {
        StringRedisTemplate redisTemplate = applicationContext.getBean(StringRedisTemplate.class);
        ObjectMapper objectMapper = getObjectMapper(applicationContext);
        return new AnyCallServerBuilder(redisTemplate, objectMapper, applicationContext);
    }

    private static ObjectMapper getObjectMapper(ApplicationContext applicationContext) {
        try {
            return applicationContext.getBean(ObjectMapper.class);
        } catch (Exception e) {
            // If no ObjectMapper bean is found, create a default one
            return new ObjectMapper();
        }
    }
}
