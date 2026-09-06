package dev.kaiquebt.anycall.exception;

public class ConnectionError extends PublishError {
    public ConnectionError(String service, String message) {
        super(service, message);
    }

    public ConnectionError(String service, String message, Throwable cause) {
        super(service, message, cause);
    }
}
