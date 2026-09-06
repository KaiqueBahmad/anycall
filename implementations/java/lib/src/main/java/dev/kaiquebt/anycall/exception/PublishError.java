package dev.kaiquebt.anycall.exception;

/**
 * Represents an error that occurs while attempting to publish a message,
 * before it has successfully left the caller. For example, a broken
 * connection, a full queue, or a timeout while waiting to hand the
 * message off to the transport.
 *
 * <p>This is distinct from errors that occur after a message has been
 * published (e.g. while awaiting a response).
 */
public class PublishError extends AnyCallError {
    public PublishError(String service, String message) {
        super(service, message);
    }

    public PublishError(String service, String message, Throwable cause) {
        super(service, message, cause);
    }
}
