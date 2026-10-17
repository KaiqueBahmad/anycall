package dev.kaiquebt.anycall.model;

import com.fasterxml.jackson.annotation.JsonInclude;

/**
 * Represents a remote procedure call response sent from the server to a client via Redis.
 * This record encapsulates the result of a remote method invocation, including the request ID,
 * response payload, and error information. Only one of payload or error will be non-null.
 * Instances are immutable and thread-safe.
 *
 * @param requestId the unique identifier matching the original request
 * @param payload the JSON-serialized result from the remote method (null if error occurred)
 * @param error a description of any error that occurred during remote method execution (null if successful)
 * @param lostServer id of the server that stopped heartbeating while processing the request;
 *                   set only on the error a reaping server writes for it
 */
public record AnyCallResponse(
    /**
     * Unique identifier matching the original request.
     */
    String requestId,

    /**
     * JSON-serialized result from the remote method execution, or null if error occurred.
     */
    String payload,

    /**
     * Error message if the remote method failed, or null if execution was successful.
     */
    String error,

    /**
     * Id of the server that stopped heartbeating while processing the request, or null.
     * Left out of the JSON when null, so every other response stays readable by clients
     * that predate the field.
     */
    @JsonInclude(JsonInclude.Include.NON_NULL)
    String lostServer
) {
    /**
     * Factory method to create a successful response.
     *
     * @param requestId the unique identifier matching the original request
     * @param payload the JSON-serialized result from the remote method
     * @return a new successful {@code AnyCallResponse}
     */
    public static AnyCallResponse success(String requestId, String payload) {
        return new AnyCallResponse(requestId, payload, null, null);
    }

    /**
     * Factory method to create an error response.
     *
     * @param requestId the unique identifier matching the original request
     * @param error a description of the error that occurred
     * @return a new error {@code AnyCallResponse}
     */
    public static AnyCallResponse error(String requestId, String error) {
        return new AnyCallResponse(requestId, null, error, null);
    }

    /**
     * Factory method to create the error response for a request whose server stopped
     * heartbeating while processing it.
     *
     * @param requestId the unique identifier matching the original request
     * @param serverId the id of the server that was lost
     * @return a new error {@code AnyCallResponse} carrying {@code lostServer}
     */
    public static AnyCallResponse serverLost(String requestId, String serverId) {
        return new AnyCallResponse(requestId, null,
            "server " + serverId + " stopped heartbeating while processing this request", serverId);
    }

    /**
     * Determines if this response represents an error condition.
     *
     * @return {@code true} if this response contains an error, {@code false} if it contains a valid payload
     */
    public boolean hasError() {
        return error != null;
    }
}
