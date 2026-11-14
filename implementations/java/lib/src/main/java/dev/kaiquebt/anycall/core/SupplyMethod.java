package dev.kaiquebt.anycall.core;

/**
 * A supply method as its object declares it, from {@link AnycallUtils#method}: what a server
 * would serve if the object were registered. For a method a server is running, with values
 * that can change, see {@link MethodInfo}.
 *
 * @param name           the name it's served under, from {@code @Supply(methodName)}
 * @param maxConcurrency its {@code @Supply(maxConcurrency)}
 * @param requestType    the type a request's payload is read into: the method's second parameter
 * @param responseType   the method's declared return type, without generic arguments. Only
 *                       informative: a server sends back whatever the method returns
 */
public record SupplyMethod(String name, int maxConcurrency, Class<?> requestType, Class<?> responseType) {
}
