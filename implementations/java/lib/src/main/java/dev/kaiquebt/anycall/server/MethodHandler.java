package dev.kaiquebt.anycall.server;

import dev.kaiquebt.anycall.core.SupplyHandler;
import dev.kaiquebt.anycall.core.SupplyMethod;

/**
 * A method a server serves: how it's declared, and what runs it. Internal.
 *
 * @param declared its name, {@code maxConcurrency}, and request and response types
 * @param handler  what runs it
 */
public record MethodHandler(SupplyMethod declared, SupplyHandler<Object, Object> handler) {

    public String methodName() {
        return declared.name();
    }

    public int maxConcurrency() {
        return declared.maxConcurrency();
    }

    public Class<?> parameterType() {
        return declared.requestType();
    }
}
