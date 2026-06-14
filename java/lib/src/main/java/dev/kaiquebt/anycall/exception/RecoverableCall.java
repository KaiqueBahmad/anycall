package dev.kaiquebt.anycall.exception;

public interface RecoverableCall {
    String getId();

    long getTTLTimestamp();
}
