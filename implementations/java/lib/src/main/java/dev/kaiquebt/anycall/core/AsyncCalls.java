package dev.kaiquebt.anycall.core;

import java.util.Map;
import java.util.concurrent.CompletableFuture;

/**
 * The calls of an {@link AnyCallClient}, returning a {@link CompletableFuture} instead of
 * blocking: {@code client.async().call(...)}. The same calls, with the same registered types,
 * settings and errors, on the same response queue; an error completes the future
 * exceptionally, wrapped in a {@link java.util.concurrent.CompletionException} as usual.
 */
public interface AsyncCalls {

    /** {@link AnyCallClient#call(String, Object, Class)}, without blocking. */
    <T> CompletableFuture<T> call(String method, Object request, Class<T> responseType);

    /** {@link AnyCallClient#call(String, Object, Class, CallOptions)}, without blocking. */
    <T> CompletableFuture<T> call(String method, Object request, Class<T> responseType, CallOptions options);

    /** {@link AnyCallClient#call(String, Object)}, without blocking. */
    <T> CompletableFuture<T> call(String method, Object request);

    /** {@link AnyCallClient#call(String, Object, CallOptions)}, without blocking. */
    <T> CompletableFuture<T> call(String method, Object request, CallOptions options);

    /** {@link AnyCallClient#rawCall(String, Object)}, without blocking. */
    CompletableFuture<Map<String, Object>> rawCall(String method, Object request);

    /** {@link AnyCallClient#rawCall(String, Object, CallOptions)}, without blocking. */
    CompletableFuture<Map<String, Object>> rawCall(String method, Object request, CallOptions options);
}
