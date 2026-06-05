package dev.kaiquebt.anycall.server;

import com.fasterxml.jackson.databind.ObjectMapper;
import dev.kaiquebt.anycall.annotation.Supply;
import dev.kaiquebt.anycall.config.AnycallProperties;
import dev.kaiquebt.anycall.core.AnyCallServer;
import dev.kaiquebt.anycall.core.RedisStreamAdapter;

import java.lang.reflect.Method;
import java.util.HashMap;
import java.util.Map;

public class AnyCallServerBuilder {

    private final RedisStreamAdapter redis;
    private final ObjectMapper objectMapper;
    private final Map<String, MethodHandler> handlers;
    private boolean metricsEnabled = false;

    public AnyCallServerBuilder(RedisStreamAdapter redis, ObjectMapper objectMapper) {
        this.redis = redis;
        this.objectMapper = objectMapper;
        this.handlers = new HashMap<>();
    }

    public AnyCallServerBuilder metrics(boolean enabled) {
        this.metricsEnabled = enabled;
        return this;
    }

    public AnyCallServerBuilder properties(AnycallProperties properties) {
        this.metricsEnabled = properties.metricsEnabled();
        return this;
    }

    public AnyCallServerBuilder register(Object supplier) {
        scanAndRegisterSupplier(supplier);
        return this;
    }

    public AnyCallServerBuilder register(Object... suppliers) {
        for (Object supplier : suppliers) {
            scanAndRegisterSupplier(supplier);
        }
        return this;
    }

    public AnyCallServerBuilder register(Iterable<?> suppliers) {
        for (Object supplier : suppliers) {
            scanAndRegisterSupplier(supplier);
        }
        return this;
    }

    public AnyCallServer start() {
        if (handlers.isEmpty()) {
            throw new IllegalStateException(
                "No methods annotated with @Supply found. " +
                "Register at least one supplier using register() method."
            );
        }

        AnyCallServer server = new AnyCallServerImpl(
            redis,
            objectMapper,
            handlers,
            metricsEnabled
        );
        return server.start();
    }

    private void scanAndRegisterSupplier(Object supplier) {
        Class<?> supplierClass = supplier.getClass();

        for (Method method : supplierClass.getDeclaredMethods()) {
            Supply supplyAnnotation = method.getAnnotation(Supply.class);

            if (supplyAnnotation != null) {
                String methodName = supplyAnnotation.value();

                if (method.getParameterCount() != 1) {
                    throw new IllegalStateException(
                        "Method " + method.getName() + " annotated with @Supply must have exactly one parameter"
                    );
                }

                Class<?> parameterType = method.getParameterTypes()[0];
                method.setAccessible(true);

                handlers.put(methodName, new MethodHandler(supplier, method, parameterType));
            }
        }
    }
}
