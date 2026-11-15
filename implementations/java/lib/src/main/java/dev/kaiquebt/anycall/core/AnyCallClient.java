package dev.kaiquebt.anycall.core;

import java.util.Map;

/**
 * Client interface for making remote procedure calls via Redis.
 * Provides synchronous interface with two distinct call paths:
 * - Typed call: call() with explicit type or registry lookup
 * - Raw call: rawCall() always returns Map (untyped)
 * <p>
 * Every call takes the client's {@link CallOptions} (given to {@link AnyCall#client}, changed
 * with {@link #updateDefaults}); one passed as the last argument replaces them for that call.
 * Close the client when done with it, or use it in a try-with-resources block.
 */
public interface AnyCallClient extends AutoCloseable {

    /**
     * Typed call: call with explicit type (fast path).
     *
     * Deserializes response JSON to the provided responseType directly.
     * Type comes from argument (trusted), not from wire.
     *
     * @param <T> the type of the response object
     * @param method the name of the remote method to invoke
     * @param request the request payload object to be serialized and sent
     * @param responseType the class type for deserializing the response
     * @return the deserialized response from the remote method
     * @throws dev.kaiquebt.anycall.exception.AnyCallError if the call fails, times out, or the remote method returns an error
     */
    <T> T call(String method, Object request, Class<T> responseType);

    /**
     * Typed call: call with explicit type and settings of its own.
     *
     * @param <T> the type of the response object
     * @param method the name of the remote method to invoke
     * @param request the request payload object to be serialized and sent
     * @param responseType the class type for deserializing the response
     * @param options this call's timeout and queue limit; a setting left out keeps the client's
     * @return the deserialized response from the remote method
     * @throws dev.kaiquebt.anycall.exception.QueueFullError if the queue is full
     * @throws dev.kaiquebt.anycall.exception.AnyCallError if the call fails, times out, or the remote method returns an error
     */
    <T> T call(String method, Object request, Class<T> responseType, CallOptions options);

    /**
     * Typed call: call with registry-resolved type.
     *
     * Looks up the response type in the local registry and deserializes to that type.
     * If the method is not registered, raises a clear error suggesting both paths:
     * "Either call with explicit type: call(op, req, YourType), or registerType first."
     *
     * @param <T> the type of the response object
     * @param method the name of the remote method to invoke
     * @param request the request payload object to be serialized and sent
     * @return the deserialized response from the remote method
     * @throws dev.kaiquebt.anycall.exception.AnyCallError if the method is not registered or if the call fails
     */
    <T> T call(String method, Object request);

    /**
     * Typed call: call with registry-resolved type and settings of its own.
     *
     * @param <T> the type of the response object
     * @param method the name of the remote method to invoke
     * @param request the request payload object to be serialized and sent
     * @param options this call's timeout and queue limit; a setting left out keeps the client's
     * @return the deserialized response from the remote method
     * @throws dev.kaiquebt.anycall.exception.QueueFullError if the queue is full
     * @throws dev.kaiquebt.anycall.exception.AnyCallError if the method is not registered or if the call fails
     */
    <T> T call(String method, Object request, CallOptions options);

    /**
     * Raw call: call always returning untyped Map.
     *
     * Never resolves from registry; always returns Map<String,Object>.
     * Use when you want data without a model.
     *
     * @param method the name of the remote method to invoke
     * @param request the request payload object to be serialized and sent
     * @return raw response as Map<String,Object> (native structure)
     * @throws dev.kaiquebt.anycall.exception.AnyCallError if the call fails or times out
     */
    Map<String, Object> rawCall(String method, Object request);

    /**
     * Raw call: call always returning untyped Map, with settings of its own.
     *
     * @param method the name of the remote method to invoke
     * @param request the request payload object to be serialized and sent
     * @param options this call's timeout and queue limit; a setting left out keeps the client's
     * @return raw response as Map<String,Object> (native structure)
     * @throws dev.kaiquebt.anycall.exception.QueueFullError if the queue is full
     * @throws dev.kaiquebt.anycall.exception.AnyCallError if the call fails or times out
     */
    Map<String, Object> rawCall(String method, Object request, CallOptions options);

    /**
     * Reads the current backlog of a method's request queue ({@code LLEN}).
     * <p>
     * Read-only and non-destructive; safe to poll as a health gauge. A request leaves the
     * queue as soon as a server takes it, so this counts only requests still waiting, not the
     * ones being processed: the same number a queue limit is checked against.
     *
     * @param method the name of the remote method
     * @return the number of entries currently in the method's request queue
     */
    long queueDepth(String method);

    /**
     * The settings every call takes unless its own options replace them, both set: a timeout
     * or no timeout, a queue limit or no limit.
     *
     * @return a snapshot of the client's defaults
     */
    CallOptions defaults();

    /**
     * Changes the client's defaults for calls made from now on; calls already waiting keep
     * theirs. What {@code options} set replaces the client's, and what they leave out stays
     * as it is:
     *
     * <pre>{@code
     * client.updateDefaults(CallOptions.DEFAULT.withMaxQueueDepth(200));   // only the queue limit
     * }</pre>
     *
     * Safe to call from any thread.
     */
    void updateDefaults(CallOptions options);

    /**
     * Register response type for a method.
     *
     * Write-once semantics:
     * - First registration succeeds
     * - Re-registering with SAME type is idempotent (no-op)
     * - Re-registering with DIFFERENT type raises AnyCallError
     *
     * @param method method name
     * @param responseType response type for deserialization
     * @throws dev.kaiquebt.anycall.exception.AnyCallError if the method is already registered with a different type
     */
    void registerType(String method, Class<?> responseType);

    /**
     * The same calls, returning a {@code CompletableFuture} instead of blocking:
     * {@code client.async().call(...)}. They share this client's response queue, registered
     * types and settings.
     *
     * @return the asynchronous view of this client
     */
    AsyncCalls async();

    /**
     * Closes the client at once: calls still waiting fail with
     * {@link dev.kaiquebt.anycall.exception.ClientClosedError}, as does any call made after,
     * and the client's connections and reader thread are gone when this returns. A request
     * already published may still be processed by a server; its response is dropped.
     * Closing again does nothing.
     */
    @Override
    void close();
}
