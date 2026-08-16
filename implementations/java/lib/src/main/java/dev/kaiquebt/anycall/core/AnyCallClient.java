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
     * Typed raia: call with explicit type, rejecting at submission if the
     * method's request queue is already at or above {@code maxQueueDepth}.
     * Overrides the client's default {@code maxQueueDepth} for this call only.
     *
     * @param <T> the type of the response object
     * @param methodName the name of the remote method to invoke
     * @param request the request payload object to be serialized and sent
     * @param responseType the class type for deserializing the response
     * @param maxQueueDepth reject with {@link dev.kaiquebt.anycall.exception.QueueFullError}
     *        if the request queue's length is at or above this value
     * @return the deserialized response from the remote method
     * @throws dev.kaiquebt.anycall.exception.QueueFullError if the queue is full
     * @throws dev.kaiquebt.anycall.exception.AnyCallException if the call fails, times out, or the remote method returns an error
     */
    <T> T call(String methodName, Object request, Class<T> responseType, long maxQueueDepth);

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
     * Typed raia: call with registry-resolved type, rejecting at submission
     * if the method's request queue is already at or above {@code maxQueueDepth}.
     * Overrides the client's default {@code maxQueueDepth} for this call only.
     *
     * @param <T> the type of the response object
     * @param methodName the name of the remote method to invoke
     * @param request the request payload object to be serialized and sent
     * @param maxQueueDepth reject with {@link dev.kaiquebt.anycall.exception.QueueFullError}
     *        if the request queue's length is at or above this value
     * @return the deserialized response from the remote method
     * @throws dev.kaiquebt.anycall.exception.QueueFullError if the queue is full
     * @throws dev.kaiquebt.anycall.exception.AnyCallException if the operation is not registered or if the call fails
     */
    <T> T call(String methodName, Object request, long maxQueueDepth);

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
     * Raw raia: call always returning untyped Map, rejecting at submission
     * if the method's request queue is already at or above {@code maxQueueDepth}.
     * Overrides the client's default {@code maxQueueDepth} for this call only.
     *
     * @param methodName the name of the remote method to invoke
     * @param request the request payload object to be serialized and sent
     * @param maxQueueDepth reject with {@link dev.kaiquebt.anycall.exception.QueueFullError}
     *        if the request queue's length is at or above this value
     * @return raw response as Map<String,Object> (native structure)
     * @throws dev.kaiquebt.anycall.exception.QueueFullError if the queue is full
     * @throws dev.kaiquebt.anycall.exception.AnyCallException if the call fails or times out
     */
    java.util.Map<String, Object> rawCall(String methodName, Object request, long maxQueueDepth);

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
     * this client that don't pass a per-call override. Takes effect
     * immediately for subsequent calls; in-flight calls are unaffected.
     * Safe to call from any thread.
     *
     * @param maxQueueDepth new default backlog limit, or {@code null} to make
     *                      calls unbounded again
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
}
