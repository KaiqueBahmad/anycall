package dev.kaiquebt.anycall.exception;

public class ChannelClosedError extends ChannelError implements RecoverableCall {
    private final String reason;
    private final String callId;
    private final long ttlTimestamp;

    public ChannelClosedError(String service, String message, String reason, String callId, long ttlTimestamp) {
        super(service, message);
        this.reason = reason;
        this.callId = callId;
        this.ttlTimestamp = ttlTimestamp;
    }

    public String getReason() {
        return reason;
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
