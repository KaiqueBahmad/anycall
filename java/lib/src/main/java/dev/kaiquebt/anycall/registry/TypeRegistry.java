package dev.kaiquebt.anycall.registry;

import dev.kaiquebt.anycall.exception.AnyCallError;
import java.util.concurrent.ConcurrentHashMap;

/**
 * Registry of response types for operations (write-once, mostly-read).
 *
 * Thread-safe using ConcurrentHashMap with putIfAbsent semantics.
 * Each operation is registered once (typically at startup) and then only read;
 * no RMW loops, no contention on same key.
 */
public class TypeRegistry {

    private final ConcurrentHashMap<String, Class<?>> types = new ConcurrentHashMap<>();

    /**
     * Register a response type for an operation.
     *
     * Write-once semantics:
     * - First registration succeeds
     * - Re-registering with SAME type is idempotent (no-op)
     * - Re-registering with DIFFERENT type raises AnyCallException
     *
     * @param operation operation name
     * @param responseType response type for deserialization
     * @throws AnyCallException if operation already registered with different type
     */
    public void register(String operation, Class<?> responseType) {
        Class<?> existing = types.putIfAbsent(operation, responseType);

        if (existing != null && existing != responseType) {
            throw new AnyCallError(
                String.format(
                    "Operation '%s' already registered with type %s, cannot register %s. "
                        + "Either register with same type (idempotent) or recreate client.",
                    operation,
                    existing.getSimpleName(),
                    responseType.getSimpleName()
                )
            );
        }
    }

    /**
     * Retrieve registered response type for operation.
     *
     * @param operation operation name
     * @return response type if registered, null otherwise
     */
    public Class<?> get(String operation) {
        return types.get(operation);
    }

    /**
     * Check if operation has registered type.
     *
     * @param operation operation name
     * @return true if registered, false otherwise
     */
    public boolean has(String operation) {
        return types.containsKey(operation);
    }
}
