package dev.kaiquebt.anycall.client;

import dev.kaiquebt.anycall.exception.AnyCallError;
import dev.kaiquebt.anycall.registry.TypeRegistry;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.*;

@DisplayName("TypeRegistry Tests")
class TypeRegistryTest {

    private TypeRegistry registry;

    static class MockResponse {
        public String value;
    }

    static class AlternativeResponse {
        public int count;
    }

    @BeforeEach
    void setUp() {
        registry = new TypeRegistry();
    }

    @Test
    @DisplayName("First registration succeeds")
    void testRegisterFirstTime() {
        registry.register("my-op", MockResponse.class);
        assertTrue(registry.has("my-op"));
        assertSame(MockResponse.class, registry.get("my-op"));
    }

    @Test
    @DisplayName("Re-registering same type is idempotent")
    void testRegisterSameTypeIdempotent() {
        registry.register("my-op", MockResponse.class);
        registry.register("my-op", MockResponse.class); // Should not throw
        assertSame(MockResponse.class, registry.get("my-op"));
    }

    @Test
    @DisplayName("Re-registering different type throws error")
    void testRegisterDifferentTypeThrows() {
        registry.register("my-op", MockResponse.class);

        AnyCallError exception =
            assertThrows(
                AnyCallError.class,
                () -> registry.register("my-op", AlternativeResponse.class)
            );

        String errorMsg = exception.getMessage();
        assertTrue(errorMsg.contains("my-op"));
        assertTrue(errorMsg.contains("already registered"));
        assertTrue(errorMsg.contains("MockResponse"));
        assertTrue(errorMsg.contains("AlternativeResponse"));
    }

    @Test
    @DisplayName("Different operations can be registered independently")
    void testRegisterMultipleOperations() {
        registry.register("op1", MockResponse.class);
        registry.register("op2", AlternativeResponse.class);

        assertSame(MockResponse.class, registry.get("op1"));
        assertSame(AlternativeResponse.class, registry.get("op2"));
    }

    @Test
    @DisplayName("Get returns null for unregistered operation")
    void testGetUnregisteredReturnsNull() {
        assertNull(registry.get("unknown-op"));
    }

    @Test
    @DisplayName("Has returns false for unregistered operation")
    void testHasUnregisteredReturnsFalse() {
        assertFalse(registry.has("unknown-op"));
    }
}
