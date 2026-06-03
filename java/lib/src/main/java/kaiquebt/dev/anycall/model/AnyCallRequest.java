package kaiquebt.dev.anycall.model;

import java.util.UUID;

/**
 * Represents a remote procedure call request sent from a client to the server via Redis.
 * This record encapsulates all necessary information for invoking a remote method,
 * including a unique request identifier, the target method name, and serialized parameters.
 * Instances are immutable and thread-safe.
 *
 * @param requestId a unique identifier for this request, used to correlate responses
 * @param methodName the name of the remote method to invoke
 * @param payload the JSON-serialized request payload containing method parameters
 */
public record AnyCallRequest(
    /**
     * Unique identifier for this request.
     */
    String requestId,

    /**
     * Name of the remote method to invoke.
     */
    String methodName,

    /**
     * JSON-serialized request payload containing method parameters.
     */
    String payload
) {
    /**
     * Factory method to create a new AnyCallRequest with a randomly generated request ID.
     *
     * @param methodName the name of the remote method to invoke
     * @param payload the JSON-serialized request payload
     * @return a new {@code AnyCallRequest} with a generated UUID-based request ID
     */
    public static AnyCallRequest create(String methodName, String payload) {
        return new AnyCallRequest(UUID.randomUUID().toString(), methodName, payload);
    }
}
