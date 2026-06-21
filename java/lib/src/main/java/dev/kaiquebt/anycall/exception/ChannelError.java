package dev.kaiquebt.anycall.exception;

public class ChannelError extends AnyCallError {
    public ChannelError(String service, String message) {
        super(service, message);
    }

    public ChannelError(String service, String message, Throwable cause) {
        super(service, message, cause);
    }
}
