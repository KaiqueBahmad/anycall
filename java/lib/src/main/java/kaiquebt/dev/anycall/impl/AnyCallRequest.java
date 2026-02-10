package kaiquebt.dev.anycall.impl;

import java.util.UUID;

/**
 * Represents a request sent from client to server via Redis.
 */
public record AnyCallRequest(
    String requestId,
    String methodName,
    String payload
) {
    public static AnyCallRequest create(String methodName, String payload) {
        return new AnyCallRequest(UUID.randomUUID().toString(), methodName, payload);
    }
}
