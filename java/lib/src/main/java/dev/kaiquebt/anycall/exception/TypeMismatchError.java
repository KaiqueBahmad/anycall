package dev.kaiquebt.anycall.exception;

public class TypeMismatchError extends SerializationError {
    private final String expectedType;
    private final String actualType;
    private final String rawJson;

    public TypeMismatchError(String service, String message, String expectedType, String actualType, String rawJson) {
        super(service, message);
        this.expectedType = expectedType;
        this.actualType = actualType;
        this.rawJson = rawJson;
    }

    public String getExpectedType() {
        return expectedType;
    }

    public String getActualType() {
        return actualType;
    }

    public String getRawJson() {
        return rawJson;
    }
}
