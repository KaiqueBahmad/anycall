package dev.kaiquebt.anycall.core;

/**
 * Client interface for making remote procedure calls via Redis.
 * Provides synchronous interface with two distinct call paths:
 * - Typed raia: call() with explicit type or registry lookup
 * - Raw raia: rawCall() always returns Map (untyped)
 */
public interface AnyCallClient {

    /**
     * Typed raia: call with explicit type (fast path).
     *
     * Deserializes response JSON to the provided responseType directly.
     * Type comes from argument (trusted), not from wire.
     *
     * @param <T> the type of the response object
     * @param methodName the name of the remote method to invoke
     * @param request the request payload object to be serialized and sent
     * @param responseType the class type for deserializing the response
     * @return the deserialized response from the remote method
     * @throws dev.kaiquebt.anycall.exception.AnyCallException if the call fails, times out, or the remote method returns an error
     */
    <T> T call(String methodName, Object request, Class<T> responseType);

    /**
     * Typed raia: call with registry-resolved type.
     *
     * Looks up the response type in the local registry and deserializes to that type.
     * If operation is not registered, raises a clear error suggesting both paths:
     * "Either call with explicit type: call(op, req, YourType), or register_type first."
     *
     * @param <T> the type of the response object
     * @param methodName the name of the remote method to invoke
     * @param request the request payload object to be serialized and sent
     * @return the deserialized response from the remote method
     * @throws dev.kaiquebt.anycall.exception.AnyCallException if the operation is not registered or if the call fails
     */
    <T> T call(String methodName, Object request);

    /**
     * Raw raia: call always returning untyped Map.
     *
     * Never resolves from registry; always returns Map<String,Object>.
     * Use when you want data without a model.
     *
     * @param methodName the name of the remote method to invoke
     * @param request the request payload object to be serialized and sent
     * @return raw response as Map<String,Object> (native structure)
     * @throws dev.kaiquebt.anycall.exception.AnyCallException if the call fails or times out
     */
    java.util.Map<String, Object> rawCall(String methodName, Object request);

    /**
     * Register response type for an operation.
     *
     * Write-once semantics:
     * - First registration succeeds
     * - Re-registering with SAME type is idempotent (no-op)
     * - Re-registering with DIFFERENT type raises AnyCallException
     *
     * @param operation operation name
     * @param responseType response type for deserialization
     * @throws dev.kaiquebt.anycall.exception.AnyCallException if operation already registered with different type
     */
    void registerType(String operation, Class<?> responseType);
}
