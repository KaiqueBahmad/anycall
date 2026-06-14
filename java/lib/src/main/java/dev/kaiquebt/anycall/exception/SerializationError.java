package dev.kaiquebt.anycall.exception;

public class SerializationError extends AnyCallError {
    public SerializationError(String service, String message) {
        super(service, message);
    }
}
