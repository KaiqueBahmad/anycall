package dev.kaiquebt.anycall.core;

import dev.kaiquebt.anycall.annotation.Supply;
import org.junit.jupiter.api.Test;

import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.*;

class AnyCallUtilsTest {

    @AnyCallSupplier
    static class Methods {
        @Supply(methodName = "slow", maxConcurrency = 4)
        public Map<String, String> slow(AnyCallContext ctx, Map<String, String> req) {
            return req;
        }

        @Supply(methodName = "echo")
        public Map<String, String> echo(AnyCallContext ctx, Map<String, String> req) {
            return req;
        }

        public void notSupplied() {
        }
    }

    @AnyCallSupplier
    static class Broken {
        @Supply(methodName = "broken")
        public Object broken(Map<String, String> req) {
            return req;
        }
    }

    @Test
    void methodsListsTheSupplyMethodsSorted() {
        assertEquals(List.of("echo", "slow"), AnyCallUtils.methods(new Methods()));
    }

    @Test
    void methodsOfAnObjectWithNoneIsEmpty() {
        assertEquals(List.of(), AnyCallUtils.methods(new Object()));
    }

    @Test
    void methodReadsWhatTheObjectDeclares() {
        SupplyMethod slow = AnyCallUtils.method(new Methods(), "slow");
        assertEquals("slow", slow.name());
        assertEquals(4, slow.maxConcurrency());
        assertEquals("java.util.Map<java.lang.String, java.lang.String>", slow.requestType().getTypeName());
        assertEquals("java.util.Map<java.lang.String, java.lang.String>", slow.responseType().getTypeName());
        assertEquals(1, AnyCallUtils.method(new Methods(), "echo").maxConcurrency());
    }

    @Test
    void methodNotDeclaredFails() {
        assertThrows(IllegalArgumentException.class, () -> AnyCallUtils.method(new Methods(), "missing"));
        assertThrows(IllegalArgumentException.class, () -> AnyCallUtils.method(new Methods(), "notSupplied"));
    }

    @Test
    void anInvalidSupplyMethodIsRejectedAsAServerWould() {
        assertThrows(IllegalStateException.class, () -> AnyCallUtils.methods(new Broken()));
    }
}
