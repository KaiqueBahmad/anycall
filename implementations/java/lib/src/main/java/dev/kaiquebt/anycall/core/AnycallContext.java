package dev.kaiquebt.anycall.core;

/**
 * Per-invocation context passed as the first parameter to every {@code @Supply} method.
 * Reserved for future additions (e.g. auth, tracing, metadata) without requiring
 * another change to the {@code @Supply} method signature.
 */
public class AnycallContext {

    private final String requestId;
    private final String methodName;

    public AnycallContext(String requestId, String methodName) {
        this.requestId = requestId;
        this.methodName = methodName;
    }

    /**
     * @return the unique identifier of the request being processed
     */
    public String getRequestId() {
        return requestId;
    }

    /**
     * @return the {@code @Supply} operation name handling the request
     */
    public String getMethodName() {
        return methodName;
    }
}
