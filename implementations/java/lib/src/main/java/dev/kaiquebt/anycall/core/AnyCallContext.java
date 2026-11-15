package dev.kaiquebt.anycall.core;

/**
 * Per-invocation context passed as the first parameter to every {@code @Supply} method.
 * Reserved for future additions (e.g. auth, tracing, metadata) without requiring
 * another change to the {@code @Supply} method signature.
 *
 * @param requestId  the unique identifier of the request being processed
 * @param methodName the {@code @Supply} operation name handling the request
 */
public record AnyCallContext(String requestId, String methodName) {
}
