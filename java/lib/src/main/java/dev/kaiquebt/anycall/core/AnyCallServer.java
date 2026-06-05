package dev.kaiquebt.anycall.core;

/**
 * Server interface for processing remote procedure calls from Redis.
 * Manages the lifecycle and state of an AnyCall server that listens for and processes remote method invocations.
 */
public interface AnyCallServer {

    /**
     * Starts the server and begins processing incoming requests from Redis.
     * Launches worker threads for each registered method and begins listening on the corresponding streams.
     * This method is idempotent - calling it multiple times on an already running server has no effect.
     *
     * @return this server instance for method chaining
     */
    AnyCallServer start();

    /**
     * Stops the server and shuts down all worker threads.
     * Gracefully stops listening for new requests and terminates executor threads.
     * This method is idempotent - calling it multiple times on an already stopped server has no effect.
     */
    void stop();

    /**
     * Checks if the server is currently running and processing requests.
     *
     * @return {@code true} if the server is running, {@code false} otherwise
     */
    boolean isRunning();
}
