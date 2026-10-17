package dev.kaiquebt.anycall.exception;

/**
 * Raised when the server processing a call stopped heartbeating before it responded,
 * so no response will ever come.
 * <p>
 * Detected by another live server (heartbeat reaping), about 8–10s after the server
 * went quiet, or with none left, by the waiting client itself (waiter-driven reaping)
 * 30–60s after. The request had started and may have partially run; it is not retried.
 * Not seeing this error does not mean the server is alive: a server lost within the
 * last few seconds of a call's timeout still surfaces as a {@link TimeoutError}.
 */
public class ServerLostError extends PublishError {
    private final String callId;
    private final String serverId;

    public ServerLostError(String service, String message, String callId, String serverId) {
        super(service, message);
        this.callId = callId;
        this.serverId = serverId;
    }

    public String getId() {
        return callId;
    }

    public String getServerId() {
        return serverId;
    }
}
