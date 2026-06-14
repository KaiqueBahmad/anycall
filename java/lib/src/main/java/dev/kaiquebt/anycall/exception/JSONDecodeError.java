package dev.kaiquebt.anycall.exception;

public class JSONDecodeError extends SerializationError {
    public JSONDecodeError(String service, String message) {
        super(service, message);
    }
}
