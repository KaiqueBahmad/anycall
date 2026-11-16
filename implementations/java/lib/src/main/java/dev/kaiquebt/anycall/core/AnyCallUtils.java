package dev.kaiquebt.anycall.core;

import dev.kaiquebt.anycall.payload.Payloads;
import dev.kaiquebt.anycall.server.MethodHandler;
import dev.kaiquebt.anycall.server.SupplyScanner;

import java.lang.reflect.Type;
import java.util.List;

/**
 * Looks at a supplier object without a server: which methods it would serve and how. Checks
 * the object the way {@link AnyCallServer#register} does, so what this accepts a server
 * registers, and what it rejects a server rejects too. Also checks a type the way a call does.
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
     * Checks that {@code type} is a payload type, as registering a method or a type, or calling
     * with one, checks it: what JSON itself has (see LIBRARY.md).
     *
     * @throws IllegalArgumentException naming the field whose type isn't one
     */
    public static void checkPayloadType(Type type) {
        checkPayloadType(type, type == null ? "the type" : type.getTypeName());
    }

    /**
     * {@link #checkPayloadType(Type)}, with {@code what} naming the type in the error, such as
     * "method embed's response".
     *
     * @throws IllegalArgumentException naming the field whose type isn't one
     */
    public static void checkPayloadType(Type type, String what) {
        Payloads.checkType(type, what);
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
