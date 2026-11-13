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
     * Id of the client that made the call: its response goes to that client's queue,
     * {@code anycall:responses:<clientId>}.
     */
    String clientId,

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
     * @param clientId the id of the calling client, whose queue the response goes to
     * @return a new {@code AnyCallRequest} with a generated UUID-based request ID
     */
    public static AnyCallRequest create(String methodName, String payload, String clientId) {
        return new AnyCallRequest(UUID.randomUUID().toString(), clientId, methodName, payload);
    }

    /** Where a request's response goes: its client's queue, and the request id it carries. */
    public record ReplyAddress(String requestId, String clientId) {
    }

    /**
     * The {@code requestId} and {@code clientId} of a request entry, read on their own, or
     * {@code null} if either is missing: the entry isn't a JSON object, or one of them isn't a
     * non-empty string.
     * <p>
     * For entries the strict read rejects (an unknown or missing field), so their error can
     * still reach the client waiting for them.
     *
     * @param json the request entry exactly as it was taken
     * @return where its response goes, or {@code null}
     */
    public static ReplyAddress readReplyAddress(String json) {
        String requestId = readField(json, "requestId");
        String clientId = readField(json, "clientId");
        return requestId == null || clientId == null ? null : new ReplyAddress(requestId, clientId);
    }

    /**
     * A string field of a JSON object, read on its own, or {@code null} if the entry isn't a
     * JSON object or the field isn't a non-empty string. Also what a client hands a response
     * to its call by: its {@code requestId}, before the strict read.
     */
    public static String readField(String json, String field) {
        JsonNode node;
        try {
            node = MAPPER.readTree(json);
        } catch (Exception e) {
            return null;
        }
        if (node == null || !node.isObject()) {
            return null;
        }
        JsonNode value = node.get(field);
        if (value == null || !value.isTextual() || value.asText().isEmpty()) {
            return null;
        }
        return value.asText();
    }
}
