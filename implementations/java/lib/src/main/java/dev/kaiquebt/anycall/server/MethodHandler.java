package dev.kaiquebt.anycall.server;

import dev.kaiquebt.anycall.core.SupplyMethod;

import java.lang.reflect.Method;

/**
 * A remotely callable method found on a supplier object: what a server needs to invoke it
 * when one of its requests arrives. Internal; see {@link SupplyScanner}.
 *
 * @param methodName     the name it's served under, from {@code @Supply(methodName)}
 * @param bean           the object instance containing the method
 * @param method         the Method object to invoke
 * @param parameterType  the class type of the request, its second parameter
 * @param maxConcurrency its {@code @Supply(maxConcurrency)}
 */
public record MethodHandler(String methodName, Object bean, Method method, Class<?> parameterType,
                            int maxConcurrency) {

    /** The method as declared: its {@code @Supply} values and its request and response types. */
    public SupplyMethod declared() {
        return new SupplyMethod(methodName, maxConcurrency, parameterType, method.getReturnType());
    }
}
