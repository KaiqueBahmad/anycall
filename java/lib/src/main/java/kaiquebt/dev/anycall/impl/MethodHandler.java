package kaiquebt.dev.anycall.impl;

import java.lang.reflect.Method;

/**
 * Represents a handler for a specific method that can be called remotely.
 */
record MethodHandler(
    Object bean,
    Method method,
    Class<?> parameterType
) {
}
