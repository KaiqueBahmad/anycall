package dev.kaiquebt.anycall.core;

/**
 * Per-invocation context passed as the first parameter to every {@code @Supply} method.
 * Currently carries no data; reserved for future additions (e.g. auth, tracing, metadata)
 * without requiring another change to the {@code @Supply} method signature.
 */
public class AnycallContext {
}
