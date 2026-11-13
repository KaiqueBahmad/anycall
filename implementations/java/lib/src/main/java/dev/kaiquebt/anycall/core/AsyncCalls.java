package dev.kaiquebt.anycall.core;

import java.util.Map;
import java.util.concurrent.CompletableFuture;

/**
 * The calls of an {@link AnyCallClient}, returning a {@link CompletableFuture} instead of
 * blocking: {@code client.async().call(...)}. The same calls, with the same registered types,
 * timeout and errors, on the same response queue; an error completes the future
 * exceptionally, wrapped in a {@link java.util.concurrent.CompletionException} as usual.
 */
public interface AsyncCalls {

    /** {@link AnyCallClient#call(String, Object, Class)}, without blocking. */
    <T> CompletableFuture<T> call(String methodName, Object request, Class<T> responseType);

    /** {@link AnyCallClient#call(String, Object, Class, long)}, without blocking. */
    <T> CompletableFuture<T> call(String methodName, Object request, Class<T> responseType, long maxQueueDepth);

    /** {@link AnyCallClient#call(String, Object)}, without blocking. */
    <T> CompletableFuture<T> call(String methodName, Object request);

    /** {@link AnyCallClient#call(String, Object, long)}, without blocking. */
    <T> CompletableFuture<T> call(String methodName, Object request, long maxQueueDepth);

    /** {@link AnyCallClient#rawCall(String, Object)}, without blocking. */
    CompletableFuture<Map<String, Object>> rawCall(String methodName, Object request);

    /** {@link AnyCallClient#rawCall(String, Object, long)}, without blocking. */
    CompletableFuture<Map<String, Object>> rawCall(String methodName, Object request, long maxQueueDepth);
}
