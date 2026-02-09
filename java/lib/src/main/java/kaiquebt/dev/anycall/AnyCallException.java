package kaiquebt.dev.anycall;

/**
 * Exception thrown when an AnyCall operation fails.
 */
public class AnyCallException extends RuntimeException {

    public AnyCallException(String message) {
        super(message);
    }

    public AnyCallException(String message, Throwable cause) {
        super(message, cause);
    }
}
