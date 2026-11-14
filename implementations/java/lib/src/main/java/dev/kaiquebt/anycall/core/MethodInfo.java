package dev.kaiquebt.anycall.core;

/**
 * A snapshot of one method a server serves, from {@link AnyCallServer#method(String)}.
 *
 * @param name           the method's name, as in {@code @Supply(methodName)}
 * @param maxConcurrency how many of its requests the server processes at once: its
 *                       {@code @Supply(maxConcurrency)}, unless changed with
 *                       {@link AnyCallServer#setMaxConcurrency}
 * @param running        how many of its requests the server is processing right now
 */
public record MethodInfo(String name, int maxConcurrency, int running) {
}
