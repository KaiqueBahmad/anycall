package dev.kaiquebt.anycall.exception;

public class TimeoutError extends ChannelError implements RecoverableCall {
    private final long timeoutMs;
    private final String callId;
    private final long ttlTimestamp;

    public TimeoutError(String service, String message, long timeoutMs, String callId, long ttlTimestamp) {
        super(service, message);
        this.timeoutMs = timeoutMs;
        this.callId = callId;
        this.ttlTimestamp = ttlTimestamp;
    }

    public long getTimeoutMs() {
        return timeoutMs;
    }

    @Override
    public String getId() {
        return callId;
    }

    @Override
    public long getTTLTimestamp() {
        return ttlTimestamp;
    }
}
