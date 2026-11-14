package dev.kaiquebt.anycall.core;

/**
 * Client interface for making remote procedure calls via Redis.
 * Provides synchronous interface with two distinct call paths:
 * - Typed call: call() with explicit type or registry lookup
 * - Raw call: rawCall() always returns Map (untyped)
 */
public interface AnyCallClient {

    /**
     * Typed call: call with explicit type (fast path).
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
     * Typed call: call with explicit type, with settings for this call only that replace the
     * client's (see {@link CallOverrides}).
     *
     * @param <T> the type of the response object
     * @param methodName the name of the remote method to invoke
     * @param request the request payload object to be serialized and sent
     * @param responseType the class type for deserializing the response
     * @param overrides this call's timeout and queue limit, where they differ from the client's
     * @return the deserialized response from the remote method
     * @throws dev.kaiquebt.anycall.exception.QueueFullError if the queue is full
     * @throws dev.kaiquebt.anycall.exception.AnyCallException if the call fails, times out, or the remote method returns an error
     */
    <T> T call(String methodName, Object request, Class<T> responseType, CallOverrides overrides);

    /**
     * Typed call: call with registry-resolved type.
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
     * Typed call: call with registry-resolved type, with settings for this call only that
     * replace the client's (see {@link CallOverrides}).
     *
     * @param <T> the type of the response object
     * @param methodName the name of the remote method to invoke
     * @param request the request payload object to be serialized and sent
     * @param overrides this call's timeout and queue limit, where they differ from the client's
     * @return the deserialized response from the remote method
     * @throws dev.kaiquebt.anycall.exception.QueueFullError if the queue is full
     * @throws dev.kaiquebt.anycall.exception.AnyCallException if the operation is not registered or if the call fails
     */
    <T> T call(String methodName, Object request, CallOverrides overrides);

    /**
     * Raw call: call always returning untyped Map.
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
     * Raw call: call always returning untyped Map, with settings for this call only that
     * replace the client's (see {@link CallOverrides}).
     *
     * @param methodName the name of the remote method to invoke
     * @param request the request payload object to be serialized and sent
     * @param overrides this call's timeout and queue limit, where they differ from the client's
     * @return raw response as Map<String,Object> (native structure)
     * @throws dev.kaiquebt.anycall.exception.QueueFullError if the queue is full
     * @throws dev.kaiquebt.anycall.exception.AnyCallException if the call fails or times out
     */
    java.util.Map<String, Object> rawCall(String methodName, Object request, CallOverrides overrides);

    /**
     * Reads the current backlog of a method's request queue ({@code LLEN}).
     * <p>
     * Read-only and non-destructive; safe to poll as a health gauge. A worker's
     * {@code BRPOP} removes each request the moment it's popped, before
     * processing starts — so this reflects only requests not yet picked up by
     * any worker, not the true in-flight count (a request already being
     * processed no longer counts against this).
     *
     * @param methodName the name of the remote method
     * @return the number of entries currently in the method's request queue
     */
    long getQueueDepth(String methodName);

    /**
     * Changes the default {@code maxQueueDepth} applied to calls made through
     * this client whose overrides don't set one. Takes effect immediately for
     * subsequent calls; in-flight calls are unaffected. Safe to call from any
     * thread.
     *
     * @param maxQueueDepth new default backlog limit, at least 1, or {@code null}
     *                      to make calls unbounded again
     * @throws IllegalArgumentException if it's below 1
     */
    void setDefaultMaxQueueDepth(Long maxQueueDepth);

    /**
     * @return the client's current default {@code maxQueueDepth}, or
     *         {@code null} if calls are unbounded by default
     */
    Long getDefaultMaxQueueDepth();

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

    /**
     * The same calls, returning a {@code CompletableFuture} instead of blocking:
     * {@code client.async().call(...)}. They share this client's response queue, registered
     * types and settings.
     *
     * @return the asynchronous view of this client
     */
    AsyncCalls async();
}
