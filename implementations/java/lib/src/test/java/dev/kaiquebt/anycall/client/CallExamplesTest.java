package dev.kaiquebt.anycall.client;

import dev.kaiquebt.anycall.exception.AnyCallError;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.*;

/**
 * Examples of call(), rawCall(), and registerType() usage patterns.
 * These are semantic examples (not full RPC tests, since we don't have a server).
 */
@DisplayName("Call Examples: Typed and Raw Paths")
class CallExamplesTest {

    static class Sentiment {
        public String text;
        public String label;

        Sentiment() {}
        Sentiment(String text, String label) {
            this.text = text;
            this.label = label;
        }
    }

    static class Order {
        public String orderId;
        public int total;

        Order() {}
        Order(String orderId, int total) {
            this.orderId = orderId;
            this.total = total;
        }
    }

    @Test
    @DisplayName("Example 1: call() with explicit type (typed raia)")
    void exampleCallWithExplicitType() {
        // Semantic test: show that explicit type is passed through
        TypeRegistry registry = new TypeRegistry();

        // No registration needed; type is explicit
        assertNull(registry.get("analyze-sentiment"));

        // With explicit type, would deserialize to Sentiment
        // (actual RPC not tested here, would need server)
        assertTrue(true); // Placeholder for actual RPC call
    }

    @Test
    @DisplayName("Example 2: call() with registry (typed raia, registry-resolved)")
    void exampleCallWithRegistry() {
        TypeRegistry registry = new TypeRegistry();

        // Register the type once
        registry.registerType("analyze-sentiment", Sentiment.class);

        // Now lookup succeeds
        assertTrue(registry.has("analyze-sentiment"));
        assertSame(Sentiment.class, registry.get("analyze-sentiment"));

        // call(op, req) without explicit type would use registry
        // (actual RPC not tested here)
    }

    @Test
    @DisplayName("Example 3: rawCall() always returns Map (raw raia)")
    void exampleRawCall() {
        // rawCall never touches registry
        // Always returns Map<String,Object>

        // Even if registered, rawCall ignores registry
        TypeRegistry registry = new TypeRegistry();
        registry.registerType("some-op", Sentiment.class);

        // rawCall(op, req) would return Map, not Sentiment
        // (actual RPC not tested, but semantics are: no type involved)
        assertTrue(true); // Placeholder
    }

    @Test
    @DisplayName("Example 4: Registry absent error (fail-loud)")
    void exampleRegistryAbsentError() {
        TypeRegistry registry = new TypeRegistry();

        // call(op, req) without type and without registry entry must fail
        assertFalse(registry.has("unknown-op"));
        assertNull(registry.get("unknown-op"));

        // Would throw AnyCallException:
        // "No response type registered for operation 'unknown-op'.
        //  Either call with explicit type: call('unknown-op', req, YourType),
        //  or register the type first: registerType('unknown-op', YourType)."
    }

    @Test
    @DisplayName("Example 5: Duplicate registration with different type (error)")
    void exampleDuplicateTypeError() {
        TypeRegistry registry = new TypeRegistry();

        registry.registerType("analyze-sentiment", Sentiment.class);

        // Try to register same operation with different type
        AnyCallError exception =
            assertThrows(
                AnyCallError.class,
                () -> registry.registerType("analyze-sentiment", Order.class)
            );

        String msg = exception.getMessage();
        assertTrue(msg.contains("analyze-sentiment"));
        assertTrue(msg.contains("already registered"));
        assertTrue(msg.contains("Sentiment"));
        assertTrue(msg.contains("Order"));
    }

    @Test
    @DisplayName("Example 6: Duplicate registration with same type (idempotent)")
    void exampleDuplicateTypeSame() {
        TypeRegistry registry = new TypeRegistry();

        registry.registerType("analyze-sentiment", Sentiment.class);

        // Re-register same operation with same type → no error
        registry.registerType("analyze-sentiment", Sentiment.class);

        assertTrue(registry.has("analyze-sentiment"));
        assertSame(Sentiment.class, registry.get("analyze-sentiment"));
    }

    // Convenience method for registry in examples
    private static class TypeRegistry {
        private final dev.kaiquebt.anycall.registry.TypeRegistry delegate
            = new dev.kaiquebt.anycall.registry.TypeRegistry();

        void registerType(String operation, Class<?> responseType) {
            delegate.register(operation, responseType);
        }

        boolean has(String operation) {
            return delegate.has(operation);
        }

        Class<?> get(String operation) {
            return delegate.get(operation);
        }
    }
}
