package kaiquebt.dev.anycall;

/**
 * Represents a response sent from server to client via Redis.
 */
public record AnyCallResponse(
    String requestId,
    String payload,
    String error
) {
    public static AnyCallResponse success(String requestId, String payload) {
        return new AnyCallResponse(requestId, payload, null);
    }

    public static AnyCallResponse error(String requestId, String error) {
        return new AnyCallResponse(requestId, null, error);
    }

    public boolean hasError() {
        return error != null;
    }
}
