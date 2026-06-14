package dev.kaiquebt.anycall.exception;

public class ConnectionError extends ChannelError {
    public ConnectionError(String service, String message) {
        super(service, message);
    }
}
