package dev.kaiquebt.anycall.exception;

public class SerializationError extends AnyCallError {
    public SerializationError(String service, String message) {
        super(service, message);
    }

    public SerializationError(String service, String message, Throwable cause) {
        super(service, message, cause);
    }
}
