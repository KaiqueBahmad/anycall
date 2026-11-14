package dev.kaiquebt.anycall.core;

import dev.kaiquebt.anycall.annotation.Supply;
import org.junit.jupiter.api.Test;

import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.*;

class AnycallUtilsTest {

    @AnyCallSupplier
    static class Methods {
        @Supply(methodName = "slow", maxConcurrency = 4)
        public Map<String, Object> slow(AnycallContext ctx, Map<String, Object> req) {
            return req;
        }

        @Supply(methodName = "echo")
        public Map<String, Object> echo(AnycallContext ctx, Map<String, Object> req) {
            return req;
        }

        public void notSupplied() {
        }
    }

    @AnyCallSupplier
    static class Broken {
        @Supply(methodName = "broken")
        public Object broken(Map<String, Object> req) {
            return req;
        }
    }

    @Test
    void methodsListsTheSupplyMethodsSorted() {
        assertEquals(List.of("echo", "slow"), AnycallUtils.methods(new Methods()));
    }

    @Test
    void methodsOfAnObjectWithNoneIsEmpty() {
        assertEquals(List.of(), AnycallUtils.methods(new Object()));
    }

    @Test
    void methodReadsWhatTheObjectDeclares() {
        assertEquals(new SupplyMethod("slow", 4, Map.class, Map.class), AnycallUtils.method(new Methods(), "slow"));
        assertEquals(1, AnycallUtils.method(new Methods(), "echo").maxConcurrency());
    }

    @Test
    void methodNotDeclaredFails() {
        assertThrows(IllegalArgumentException.class, () -> AnycallUtils.method(new Methods(), "missing"));
        assertThrows(IllegalArgumentException.class, () -> AnycallUtils.method(new Methods(), "notSupplied"));
    }

    @Test
    void anInvalidSupplyMethodIsRejectedAsAServerWould() {
        assertThrows(IllegalStateException.class, () -> AnycallUtils.methods(new Broken()));
    }
}
