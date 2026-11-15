package dev.kaiquebt.anycall.core;

/**
 * What runs a method a server serves: given its request, read into the method's request type,
 * returns the response. What it throws fails the call, with its message as the error.
 *
 * @param <Q> the request type
 * @param <R> the response type
 * @see AnyCallServer#register(SupplyMethod, SupplyHandler)
 */
@FunctionalInterface
public interface SupplyHandler<Q, R> {

    R handle(AnycallContext ctx, Q request) throws Exception;
}
