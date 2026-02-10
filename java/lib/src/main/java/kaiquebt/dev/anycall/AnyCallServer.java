package kaiquebt.dev.anycall;

/**
 * Server that processes remote procedure calls from Redis.
 */
public interface AnyCallServer {

    /**
     * Starts the server and begins processing requests.
     * @return this server instance for chaining
     */
    AnyCallServer start();

    /**
     * Stops the server and shuts down all workers.
     */
    void stop();

    /**
     * Checks if the server is currently running.
     * @return true if running, false otherwise
     */
    boolean isRunning();
}
