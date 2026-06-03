package kaiquebt.dev.anycall.model;

/**
 * Represents a remote procedure call response sent from the server to a client via Redis.
 * This record encapsulates the result of a remote method invocation, including the request ID,
 * response payload, and error information. Only one of payload or error will be non-null.
 * Instances are immutable and thread-safe.
 *
 * @param requestId the unique identifier matching the original request
 * @param payload the JSON-serialized result from the remote method (null if error occurred)
 * @param error a description of any error that occurred during remote method execution (null if successful)
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
    String error
) {
    /**
     * Factory method to create a successful response.
     *
     * @param requestId the unique identifier matching the original request
     * @param payload the JSON-serialized result from the remote method
     * @return a new successful {@code AnyCallResponse}
     */
    public static AnyCallResponse success(String requestId, String payload) {
        return new AnyCallResponse(requestId, payload, null);
    }

    /**
     * Factory method to create an error response.
     *
     * @param requestId the unique identifier matching the original request
     * @param error a description of the error that occurred
     * @return a new error {@code AnyCallResponse}
     */
    public static AnyCallResponse error(String requestId, String error) {
        return new AnyCallResponse(requestId, null, error);
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
