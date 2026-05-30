package kaiquebt.dev.anycall.core;

/**
 * Client for making remote procedure calls via Redis.
 */
public interface AnyCallClient {

    /**
     * Makes a synchronous call to a remote method.
     *
     * @param methodName the name of the method to call
     * @param request the request payload
     * @param responseType the expected response type
     * @param <T> the type of the response
     * @return the response from the remote method
     * @throws AnyCallException if the call fails or times out
     */
    <T> T call(String methodName, Object request, Class<T> responseType);
}
