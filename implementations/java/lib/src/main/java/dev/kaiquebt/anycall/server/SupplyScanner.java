package dev.kaiquebt.anycall.server;

import dev.kaiquebt.anycall.annotation.Supply;
import dev.kaiquebt.anycall.core.AnycallContext;

import java.lang.reflect.Method;
import java.util.ArrayList;
import java.util.List;

/**
 * Finds the {@code @Supply} methods an object declares, checking each the way a server does
 * when it registers the object. Internal: shared by the server and
 * {@link dev.kaiquebt.anycall.core.AnycallUtils}, so both see the same methods and reject the
 * same mistakes.
 */
public final class SupplyScanner {

    private SupplyScanner() {
    }

    /**
     * The {@code @Supply} methods {@code supplier}'s class declares (not inherited ones).
     *
     * @throws IllegalStateException if one doesn't take {@code (AnycallContext, <request>)},
     *                               or has a {@code maxConcurrency} below 1
     */
    public static List<MethodHandler> scan(Object supplier) {
        List<MethodHandler> handlers = new ArrayList<>();
        for (Method method : supplier.getClass().getDeclaredMethods()) {
            Supply supply = method.getAnnotation(Supply.class);
            if (supply == null) {
                continue;
            }
            if (method.getParameterCount() != 2) {
                throw new IllegalStateException(
                    "Method " + method.getName() + " annotated with @Supply must have exactly two parameters: "
                        + "(AnycallContext, <request type>)");
            }
            if (method.getParameterTypes()[0] != AnycallContext.class) {
                throw new IllegalStateException(
                    "Method " + method.getName() + " annotated with @Supply must declare AnycallContext "
                        + "as its first parameter");
            }
            if (supply.maxConcurrency() < 1) {
                throw new IllegalStateException(
                    "Method " + method.getName() + " annotated with @Supply has invalid maxConcurrency "
                        + supply.maxConcurrency() + "; it must be at least 1");
            }
            method.setAccessible(true);
            handlers.add(new MethodHandler(supply.methodName(), supplier, method, method.getParameterTypes()[1],
                supply.maxConcurrency()));
        }
        return handlers;
    }
}
