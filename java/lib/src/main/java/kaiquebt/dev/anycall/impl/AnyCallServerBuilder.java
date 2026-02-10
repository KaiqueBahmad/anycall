package kaiquebt.dev.anycall.impl;

import com.fasterxml.jackson.databind.ObjectMapper;
import kaiquebt.dev.anycall.AnyCallServer;
import kaiquebt.dev.anycall.AnyCallSupplier;
import kaiquebt.dev.anycall.Supply;
import org.springframework.context.ApplicationContext;
import org.springframework.data.redis.core.StringRedisTemplate;

import java.lang.reflect.Method;
import java.util.HashMap;
import java.util.Map;

/**
 * Builder for creating and configuring an AnyCallServer.
 */
public class AnyCallServerBuilder {

    private final StringRedisTemplate redisTemplate;
    private final ObjectMapper objectMapper;
    private final ApplicationContext applicationContext;
    private String group = "default";

    public AnyCallServerBuilder(
        StringRedisTemplate redisTemplate,
        ObjectMapper objectMapper,
        ApplicationContext applicationContext
    ) {
        this.redisTemplate = redisTemplate;
        this.objectMapper = objectMapper;
        this.applicationContext = applicationContext;
    }

    /**
     * Sets the consumer group name.
     */
    public AnyCallServerBuilder group(String group) {
        this.group = group;
        return this;
    }

    /**
     * Builds and starts the server.
     * Scans for beans annotated with @AnyCallSupplier and registers their @Supply methods.
     */
    public AnyCallServer start() {
        Map<String, MethodHandler> methodHandlers = scanAndRegisterMethods();

        // Get metrics configuration from application context
        boolean metricsEnabled = false;
        try {
            AnycallProperties properties = applicationContext.getBean(AnycallProperties.class);
            metricsEnabled = properties.metricsEnabled();
        } catch (Exception e) {
            // Properties bean not found, use default
        }

        AnyCallServer server = new AnyCallServerImpl(
            redisTemplate,
            objectMapper,
            group,
            methodHandlers,
            metricsEnabled
        );
        return server.start();
    }

    private Map<String, MethodHandler> scanAndRegisterMethods() {
        Map<String, MethodHandler> handlers = new HashMap<>();

        // Find all beans annotated with @AnyCallSupplier
        Map<String, Object> supplierBeans = applicationContext.getBeansWithAnnotation(AnyCallSupplier.class);

        for (Object bean : supplierBeans.values()) {
            Class<?> beanClass = bean.getClass();

            // Scan all methods in the bean
            for (Method method : beanClass.getDeclaredMethods()) {
                Supply supplyAnnotation = method.getAnnotation(Supply.class);

                if (supplyAnnotation != null) {
                    String methodName = supplyAnnotation.value();

                    // Validate method signature
                    if (method.getParameterCount() != 1) {
                        throw new IllegalStateException(
                            "Method " + method.getName() + " annotated with @Supply must have exactly one parameter"
                        );
                    }

                    Class<?> parameterType = method.getParameterTypes()[0];

                    // Make the method accessible
                    method.setAccessible(true);

                    // Register the handler
                    MethodHandler handler = new MethodHandler(bean, method, parameterType);
                    handlers.put(methodName, handler);
                }
            }
        }

        if (handlers.isEmpty()) {
            throw new IllegalStateException(
                "No methods annotated with @Supply found. " +
                "Make sure you have classes annotated with @AnyCallSupplier containing @Supply methods."
            );
        }

        return handlers;
    }
}
