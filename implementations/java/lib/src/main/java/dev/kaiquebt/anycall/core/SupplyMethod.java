package dev.kaiquebt.anycall.core;

import java.lang.reflect.Type;

/**
 * A supply method as declared: from an object's {@code @Supply}, as {@link AnyCallUtils#method}
 * reads it, or given to {@link AnyCallServer#register(SupplyMethod, SupplyHandler)} with the
 * handler that runs it. For a method a server is running, with values that can change, see
 * {@link MethodInfo}.
 *
 * @param name           the name it's served under, from {@code @Supply(methodName)}
 * @param maxConcurrency its {@code @Supply(maxConcurrency)}
 * @param requestType    the type a request's payload is read into: the method's second parameter,
 *                       with its generic arguments. A payload type
 * @param responseType   the method's declared return type, with its generic arguments; a payload
 *                       type, or {@code void}. Only informative: a server sends back whatever the
 *                       method returns, checked only as a payload as it's written
 */
public record SupplyMethod(String name, int maxConcurrency, Type requestType, Type responseType) {
}
