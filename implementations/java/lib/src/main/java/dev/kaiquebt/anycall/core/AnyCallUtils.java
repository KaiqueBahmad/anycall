package dev.kaiquebt.anycall.core;

import dev.kaiquebt.anycall.server.MethodHandler;
import dev.kaiquebt.anycall.server.SupplyScanner;

import java.util.List;

/**
 * Looks at a supplier object without a server: which methods it would serve and how. Checks
 * the object the way {@link AnyCallServer#register} does, so what this accepts a server
 * registers, and what it rejects a server rejects too.
 */
public final class AnyCallUtils {

    private AnyCallUtils() {
    }

    /**
     * The names of the {@code @Supply} methods {@code supplier}'s class declares, sorted.
     *
     * @throws IllegalStateException if one of them isn't a valid supply method
     */
    public static List<String> methods(Object supplier) {
        return SupplyScanner.scan(supplier).stream().map(MethodHandler::methodName).distinct().sorted().toList();
    }

    /**
     * One {@code @Supply} method of {@code supplier}, as declared.
     *
     * @throws IllegalArgumentException if {@code supplier} declares no method under that name
     * @throws IllegalStateException    if one of its methods isn't a valid supply method
     */
    public static SupplyMethod method(Object supplier, String methodName) {
        return SupplyScanner.scan(supplier).stream()
            .filter(handler -> handler.methodName().equals(methodName))
            .reduce((first, second) -> second)
            .map(MethodHandler::declared)
            .orElseThrow(() -> new IllegalArgumentException(
                supplier.getClass().getName() + " declares no @Supply method '" + methodName + "'"));
    }
}
