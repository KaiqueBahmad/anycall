package dev.kaiquebt.anycall.exception;

public class RemoteException extends RemoteExecutionError {
    private final String exceptionType;

    public RemoteException(String service, String message, String exceptionType) {
        super(service, message);
        this.exceptionType = exceptionType;
    }

    public String getExceptionType() {
        return exceptionType;
    }
}
