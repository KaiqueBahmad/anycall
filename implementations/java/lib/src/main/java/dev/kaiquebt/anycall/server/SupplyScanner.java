package dev.kaiquebt.anycall.server;

import dev.kaiquebt.anycall.annotation.Supply;
import dev.kaiquebt.anycall.core.AnyCallContext;
import dev.kaiquebt.anycall.core.SupplyHandler;
import dev.kaiquebt.anycall.core.SupplyMethod;
import dev.kaiquebt.anycall.payload.Payloads;

import java.lang.reflect.InvocationTargetException;
import java.lang.reflect.Method;
import java.util.ArrayList;
import java.util.List;

/**
 * Finds the {@code @Supply} methods an object declares, checking each the way a server does
 * when it registers the object. Internal: shared by the server and
 * {@link dev.kaiquebt.anycall.core.AnyCallUtils}, so both see the same methods and reject the
 * same mistakes.
 */
public final class SupplyScanner {

    private SupplyScanner() {
    }

    /**
     * The {@code @Supply} methods {@code supplier}'s class declares (not inherited ones).
     *
     * @throws IllegalStateException    if one doesn't take {@code (AnyCallContext, <request>)},
     *                                  or has a {@code maxConcurrency} below 1
     * @throws IllegalArgumentException if its request or response type isn't a payload type
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
                        + "(AnyCallContext, <request type>)");
            }
            if (method.getParameterTypes()[0] != AnyCallContext.class) {
                throw new IllegalStateException(
                    "Method " + method.getName() + " annotated with @Supply must declare AnyCallContext "
                        + "as its first parameter");
            }
            if (supply.maxConcurrency() < 1) {
                throw new IllegalStateException(
                    "Method " + method.getName() + " annotated with @Supply has invalid maxConcurrency "
                        + supply.maxConcurrency() + "; it must be at least 1");
            }
            method.setAccessible(true);
            SupplyMethod declared = new SupplyMethod(supply.methodName(), supply.maxConcurrency(),
                method.getGenericParameterTypes()[1], method.getGenericReturnType());
            checkTypes(declared);
            handlers.add(new MethodHandler(declared, invoking(supplier, method)));
        }
        return handlers;
    }

    /**
     * Checks a method's request and response types are payload types; a {@code void} response
     * declares none.
     *
     * @throws IllegalArgumentException naming the field whose type isn't one
     */
    public static void checkTypes(SupplyMethod declared) {
        Payloads.checkType(declared.requestType(), "method " + declared.name() + "'s request");
        if (declared.responseType() != null && !Payloads.isVoid(declared.responseType())) {
            Payloads.checkType(declared.responseType(), "method " + declared.name() + "'s response");
        }
    }

    /**
     * Runs {@code method} on {@code supplier}, throwing what the method throws rather than the
     * {@link InvocationTargetException} reflection wraps it in.
     */
    public static SupplyHandler<Object, Object> invoking(Object supplier, Method method) {
        return (ctx, request) -> {
            try {
                return method.invoke(supplier, ctx, request);
            } catch (InvocationTargetException e) {
                if (e.getCause() instanceof Exception cause) {
                    throw cause;
                }
                if (e.getCause() instanceof Error error) {
                    throw error;
                }
                throw e;
            }
        };
    }
}
