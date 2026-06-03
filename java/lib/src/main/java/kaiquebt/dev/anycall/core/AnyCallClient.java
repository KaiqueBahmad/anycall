package kaiquebt.dev.anycall.core;

import kaiquebt.dev.anycall.exception.AnyCallException;

/**
 * Client interface for making remote procedure calls via Redis.
 * Provides a simple synchronous interface for invoking remote methods on AnyCall suppliers.
 */
public interface AnyCallClient {

    /**
     * Makes a synchronous call to a remote method via Redis.
     * Serializes the request, publishes it to the appropriate Redis queue, and waits for the response.
     * The call will block until a response is received or the timeout is reached.
     *
     * @param <T> the type of the response object
     * @param methodName the name of the remote method to invoke
     * @param request the request payload object to be serialized and sent
     * @param responseType the class type for deserializing the response
     * @return the deserialized response from the remote method
     * @throws kaiquebt.dev.anycall.exception.AnyCallException if the call fails, times out, or the remote method returns an error
     */
    <T> T call(String methodName, Object request, Class<T> responseType);
}
