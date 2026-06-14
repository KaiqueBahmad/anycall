package dev.kaiquebt.anycall.exception;

public class RemoteExecutionError extends AnyCallError {
    public RemoteExecutionError(String service, String message) {
        super(service, message);
    }
}
