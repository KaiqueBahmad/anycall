package dev.kaiquebt.anycall.exception;

public class TimeoutError extends PublishError {
    private final String callId;

    public TimeoutError(String service, String message, String callId) {
        super(service, message);
        this.callId = callId;
    }

    public String getId() {
        return callId;
    }
}
