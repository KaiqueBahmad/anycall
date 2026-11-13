package dev.kaiquebt.anycall.exception;

/**
 * Thrown when a Redis command fails during a call: the connection dropped, Redis restarted
 * or stopped answering.
 * <p>
 * {@link #isPublished()} says whether the request may have left: {@code false} when Redis
 * failed before the {@code LPUSH}, so the method certainly didn't run and the call can be
 * made again; {@code true} from the {@code LPUSH} on, so the method may have run, as with
 * {@link ServerLostError}. The Lettuce exception is the cause.
 */
public class BrokerError extends PublishError {
    private final String callId;
    private final boolean published;

    public BrokerError(String service, String message, String callId, boolean published, Throwable cause) {
        super(service, message, cause);
        this.callId = callId;
        this.published = published;
    }

    public String getId() {
        return callId;
    }

    public boolean isPublished() {
        return published;
    }
}
