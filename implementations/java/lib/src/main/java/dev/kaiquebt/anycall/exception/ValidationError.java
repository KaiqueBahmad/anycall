package dev.kaiquebt.anycall.exception;

public class ValidationError extends RemoteExecutionError {
    public ValidationError(String service, String message) {
        super(service, message);
    }
}
