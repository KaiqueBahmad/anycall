package dev.kaiquebt.anycall.server;

import dev.kaiquebt.anycall.annotation.Supply;
import dev.kaiquebt.anycall.core.AnyCallSupplier;
import dev.kaiquebt.anycall.core.AnyCallContext;
import dev.kaiquebt.anycall.core.SupplyMethod;
import org.junit.jupiter.api.Test;

import java.util.List;

import static org.junit.jupiter.api.Assertions.*;

class SupplyScannerTest {

    @AnyCallSupplier
    static class Shouter {
        @Supply(methodName = "shout", maxConcurrency = 3)
        public String shout(AnyCallContext ctx, String text) {
            if (text.isEmpty()) {
                throw new IllegalArgumentException("text is empty");
            }
            return text.toUpperCase();
        }
    }

    private final AnyCallContext ctx = new AnyCallContext("r1", "shout");

    @Test
    void aScannedMethodIsDeclaredAndRunByItsHandler() throws Exception {
        List<MethodHandler> handlers = SupplyScanner.scan(new Shouter());

        assertEquals(1, handlers.size());
        MethodHandler handler = handlers.get(0);
        assertEquals(new SupplyMethod("shout", 3, String.class, String.class), handler.declared());
        assertEquals("HI", handler.handler().handle(ctx, "hi"));
    }

    @Test
    void aHandlerThrowsWhatTheMethodThrowsNotTheReflectionWrapper() {
        MethodHandler handler = SupplyScanner.scan(new Shouter()).get(0);

        IllegalArgumentException e = assertThrows(IllegalArgumentException.class,
            () -> handler.handler().handle(ctx, ""));
        assertEquals("text is empty", e.getMessage());
    }
}
