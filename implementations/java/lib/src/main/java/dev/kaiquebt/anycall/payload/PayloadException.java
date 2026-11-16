package dev.kaiquebt.anycall.payload;

/**
 * A value that isn't a payload, or JSON that doesn't fit the type it's read into. Internal: a
 * client turns it into a {@link dev.kaiquebt.anycall.exception.SerializationError}, a server
 * into a remote error.
 */
public class PayloadException extends RuntimeException {

    public PayloadException(String message) {
        super(message);
    }
}
