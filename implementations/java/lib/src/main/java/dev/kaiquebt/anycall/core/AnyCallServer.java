package dev.kaiquebt.anycall.core;

/**
 * Server interface for processing remote procedure calls from Redis.
 * Manages the lifecycle and state of an AnyCall server that listens for and processes remote method invocations.
 */
public interface AnyCallServer {

    /**
     * Starts the server and begins processing incoming requests from Redis.
     * Spawns the single read loop that blocks on every registered method's request
     * queue and dispatches to a shared worker pool.
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

    /**
     * Registers multiple suppliers with the server.
     * Each supplier is scanned for methods annotated with @Supply.
     * If the server is already running, immediately starts listening for requests on the new methods.
     *
     * @param suppliers the objects containing methods annotated with @Supply
     * @return this server instance for method chaining
     */
    AnyCallServer register(Object... suppliers);

    /**
     * The server's settings, each set: a server-wide cap or no cap.
     *
     * @return a snapshot of the server's settings
     */
    ServerOptions options();

    /**
     * Changes the server's settings while it runs. What {@code options} set replaces the
     * server's, and what they leave out stays as it is. Lowering the server-wide cap lets the
     * requests already running finish; no new one runs until fewer than the new cap do.
     *
     * <pre>{@code
     * server.updateOptions(ServerOptions.DEFAULT.withMaxConcurrency(32));
     * }</pre>
     *
     * Safe to call from any thread.
     */
    void updateOptions(ServerOptions options);

    /**
     * The names of every registered method, sorted.
     */
    java.util.List<String> methods();

    /**
     * A snapshot of one registered method: its concurrency cap, how many of its requests are
     * running right now, and how its object declared it.
     *
     * @throws IllegalArgumentException if no method is registered under that name
     */
    MethodInfo method(String name);

    /**
     * Changes how many requests of one method this server processes at once, while it runs.
     * Raising it lets the method take more at once; lowering it lets the requests already
     * running finish, and takes no new one until fewer than the new cap run.
     *
     * @throws IllegalArgumentException if it's below 1, or no method is registered under that name
     */
    void setMaxConcurrency(String method, int maxConcurrency);

    /**
     * Unregisters a supplier method from the server.
     * Stops the listener thread for the specified method.
     *
     * @param method the name of the method to unregister (as specified in @Supply)
     * @return this server instance for method chaining
     */
    AnyCallServer unregister(String method);
}
