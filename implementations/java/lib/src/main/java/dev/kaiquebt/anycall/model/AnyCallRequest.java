package dev.kaiquebt.anycall.model;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;

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
    private static final ObjectMapper MAPPER = new ObjectMapper();

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

    /**
     * The {@code requestId} of a request entry, read on its own, or {@code null} if it has
     * none: the entry isn't a JSON object, or its {@code requestId} isn't a non-empty string.
     * <p>
     * For entries the strict read rejects (an unknown or missing field), so their error can
     * still reach the client waiting on their response queue.
     *
     * @param json the request entry exactly as it was taken
     * @return its request id, or {@code null}
     */
    public static String readRequestId(String json) {
        JsonNode node;
        try {
            node = MAPPER.readTree(json);
        } catch (Exception e) {
            return null;
        }
        if (node == null || !node.isObject()) {
            return null;
        }
        JsonNode requestId = node.get("requestId");
        if (requestId == null || !requestId.isTextual() || requestId.asText().isEmpty()) {
            return null;
        }
        return requestId.asText();
    }
}
