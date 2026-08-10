package dev.kaiquebt.anycall.exception;

/**
 * Raised when a call is rejected at submission because the target method's
 * request stream already has at least {@code maxQueueDepth} entries.
 * <p>
 * Thrown before the request is published (before {@code XADD}), so the
 * caller that would have waited for a response is the one that sees the
 * failure — instead of the request silently being dropped later by stream
 * trimming (e.g. {@code MAXLEN}) with no way to signal the original caller.
 * <p>
 * The depth check ({@code XLEN} then {@code XADD}) is advisory, not a hard
 * bound: another client can publish between the two calls, so the queue can
 * briefly exceed {@code maxQueueDepth}. A strict bound would need an atomic
 * check-and-add (e.g. a Lua script).
 */
public class QueueFullError extends ChannelError {

    private final String methodName;
    private final long queueDepth;
    private final long maxQueueDepth;

    public QueueFullError(String methodName, long queueDepth, long maxQueueDepth) {
        super("AnyCall", "Queue for method '" + methodName + "' is full: depth=" + queueDepth
            + " >= maxQueueDepth=" + maxQueueDepth);
        this.methodName = methodName;
        this.queueDepth = queueDepth;
        this.maxQueueDepth = maxQueueDepth;
    }

    public String getMethodName() {
        return methodName;
    }

    public long getQueueDepth() {
        return queueDepth;
    }

    public long getMaxQueueDepth() {
        return maxQueueDepth;
    }
}
