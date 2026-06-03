package kaiquebt.dev.anycall.exception;

/**
 * Exception thrown when an AnyCall remote procedure call operation fails.
 * This unchecked exception indicates an error occurred during the invocation,
 * serialization, deserialization, or execution of a remote method call.
 * Typical causes include timeouts, network errors, remote method errors, or JSON processing failures.
 */
public class AnyCallException extends RuntimeException {

    /**
     * Constructs a new AnyCallException with the specified error message.
     *
     * @param message the detail message explaining the failure
     */
    public AnyCallException(String message) {
        super(message);
    }

    /**
     * Constructs a new AnyCallException with the specified error message and underlying cause.
     *
     * @param message the detail message explaining the failure
     * @param cause the underlying exception that caused this AnyCall exception
     */
    public AnyCallException(String message, Throwable cause) {
        super(message, cause);
    }
}
