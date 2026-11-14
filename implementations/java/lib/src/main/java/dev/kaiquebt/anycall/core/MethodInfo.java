package dev.kaiquebt.anycall.core;

/**
 * A snapshot of one method a server serves, from {@link AnyCallServer#method(String)}.
 *
 * @param maxConcurrency how many of its requests the server processes at once: its
 *                       {@code @Supply(maxConcurrency)}, unless changed with
 *                       {@link AnyCallServer#setMaxConcurrency}
 * @param running        how many of its requests the server is processing right now
 * @param declared       the method as its object declared it when registered: its name,
 *                       {@code @Supply} values and its request and response types
 */
public record MethodInfo(int maxConcurrency, int running, SupplyMethod declared) {
}
