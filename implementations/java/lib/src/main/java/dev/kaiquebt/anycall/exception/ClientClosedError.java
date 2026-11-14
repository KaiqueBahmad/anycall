package dev.kaiquebt.anycall.exception;

/**
 * The client was closed: a call made after {@code close()} fails with this before anything
 * is published, and a call still waiting when the client closes fails with it at once. A
 * request already published may still be processed by a server; its response is dropped.
 */
public class ClientClosedError extends AnyCallError {

    public ClientClosedError(String service, String message) {
        super(service, message);
    }
}
