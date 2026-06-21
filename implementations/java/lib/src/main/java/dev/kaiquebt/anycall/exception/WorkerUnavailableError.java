package dev.kaiquebt.anycall.exception;

public class WorkerUnavailableError extends ChannelError implements RecoverableCall {
    private final String callId;
    private final long ttlTimestamp;

    public WorkerUnavailableError(String service, String message, String callId, long ttlTimestamp) {
        super(service, message);
        this.callId = callId;
        this.ttlTimestamp = ttlTimestamp;
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
