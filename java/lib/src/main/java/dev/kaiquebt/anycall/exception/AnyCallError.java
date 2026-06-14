package dev.kaiquebt.anycall.exception;

public class AnyCallError extends RuntimeException {
    private final String service;
    private final String message;

    public AnyCallError(String service, String message) {
        super(message);
        this.service = service;
        this.message = message;
    }

    public AnyCallError(String service, String message, Throwable cause) {
        super(message, cause);
        this.service = service;
        this.message = message;
    }

    public AnyCallError(String message) {
        super(message);
        this.service = "AnyCall";
        this.message = message;
    }

    public AnyCallError(String message, Throwable cause) {
        super(message, cause);
        this.service = "AnyCall";
        this.message = message;
    }

    public String getService() {
        return service;
    }

    @Override
    public String getMessage() {
        return message;
    }
}
