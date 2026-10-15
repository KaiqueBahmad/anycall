package dev.kaiquebt.anycall.exception;

/**
 * Raised when a call is rejected at submission because no server has
 * heartbeated recently enough to be considered alive.
 * <p>
 * Thrown before the request is published (before {@code LPUSH}), mirroring
 * what a connection-refused error would look like over plain HTTP: fail
 * immediately instead of queueing a request that may sit unread for the
 * full call timeout.
 * <p>
 * This check is advisory, not a guarantee: it only confirms that at least
 * one server process is heartbeating, not that any of them support the
 * requested method. A server could also heartbeat for the first time, or
 * stop heartbeating, in the moment between this check and the {@code LPUSH}.
 */
public class NoServerAvailableError extends PublishError {

    private final String methodName;

    public NoServerAvailableError(String methodName) {
        super("AnyCall", "No server is currently alive to handle method: " + methodName);
        this.methodName = methodName;
    }

    public String getMethodName() {
        return methodName;
    }
}
