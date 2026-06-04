package kaiquebt.dev.anycall.server;

import java.lang.reflect.Method;

/**
 * Represents a handler for a remotely callable method.
 * Contains the object instance, method object, and parameter type information
 * needed to invoke a method when a remote procedure call is received.
 *
 * @param bean the object instance containing the method
 * @param method the Method object to invoke
 * @param parameterType the class type of the method's single parameter
 */
record MethodHandler(
    /**
     * The object instance that contains the remote method.
     */
    Object bean,

    /**
     * The Method object representing the remotely callable method.
     */
    Method method,

    /**
     * The class type of the method's single parameter for deserialization.
     */
    Class<?> parameterType
) {
}
