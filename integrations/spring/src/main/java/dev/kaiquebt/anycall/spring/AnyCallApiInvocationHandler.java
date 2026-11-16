package dev.kaiquebt.anycall.spring;

import dev.kaiquebt.anycall.core.AnyCallClient;
import dev.kaiquebt.anycall.core.AnyCallUtils;
import dev.kaiquebt.anycall.core.CallOptions;
import org.springframework.boot.convert.DurationStyle;

import java.lang.reflect.InvocationHandler;
import java.lang.reflect.Method;
import java.lang.reflect.Modifier;
import java.lang.reflect.ParameterizedType;
import java.lang.reflect.Type;
import java.time.Duration;
import java.util.HashMap;
import java.util.Map;
import java.util.concurrent.CompletableFuture;
import java.util.function.Function;

/**
 * Turns a call to an {@link AnyCallApi} method into an AnyCall call. Every method is read once,
 * when the proxy is made, so a mistake in the interface fails the context at startup rather
 * than on the first call.
 */
class AnyCallApiInvocationHandler implements InvocationHandler {

    /** What a method's return type makes of its call. */
    private enum Shape { TYPED, RAW, DROPPED }

    /** One method, read. */
    private record RemoteCall(String method, CallOptions options, Shape shape, Class<?> responseType,
                              boolean async) {
    }

    private static final String NONE = "none";

    private final Class<?> apiInterface;
    private final AnyCallClient client;
    private final Map<Method, RemoteCall> calls = new HashMap<>();

    /**
     * @param resolve resolves the property placeholders of a {@link Call} attribute
     */
    AnyCallApiInvocationHandler(Class<?> apiInterface, AnyCallClient client, Function<String, String> resolve) {
        this.apiInterface = apiInterface;
        this.client = client;
        for (Method method : apiInterface.getMethods()) {
            if (method.isDefault() || Modifier.isStatic(method.getModifiers())
                    || method.getDeclaringClass() == Object.class) {
                continue;
            }
            calls.put(method, read(method, resolve));
        }
    }

    private static RemoteCall read(Method method, Function<String, String> resolve) {
        String where = method.getDeclaringClass().getName() + "." + method.getName();
        Call call = method.getAnnotation(Call.class);
        if (call == null) {
            throw new IllegalStateException(where + " has no @Call: every method of an @AnyCallApi interface "
                + "calls a remote method, unless it's a default method");
        }
        if (method.getParameterCount() > 1) {
            throw new IllegalStateException(where + " must take at most one argument, the request; it takes "
                + method.getParameterCount());
        }

        boolean async = method.getReturnType() == CompletableFuture.class;
        Type returned = async ? futureArgument(method, where) : method.getGenericReturnType();
        Shape shape = shape(returned, async, where);
        Class<?> responseType = shape == Shape.TYPED ? (Class<?>) returned : null;

        Function<String, String> placeholders = value -> {
            if (value.contains("#{")) {
                throw new IllegalStateException(where + " has '" + value + "': @Call reads property "
                    + "placeholders (${...}), not SpEL");
            }
            return resolve.apply(value);
        };
        return new RemoteCall(name(placeholders.apply(call.value()), where), options(call, placeholders, where),
            shape, responseType, async);
    }

    private static Type futureArgument(Method method, String where) {
        if (method.getGenericReturnType() instanceof ParameterizedType future) {
            return future.getActualTypeArguments()[0];
        }
        throw new IllegalStateException(where + " returns a raw CompletableFuture; say what it completes with, "
            + "as in CompletableFuture<Sentiment>");
    }

    private static Shape shape(Type returned, boolean async, String where) {
        if (returned == (async ? Void.class : void.class)) {
            return Shape.DROPPED;
        }
        if (returned instanceof ParameterizedType parameterized && parameterized.getRawType() == Map.class
                && parameterized.getActualTypeArguments()[0] == String.class
                && parameterized.getActualTypeArguments()[1] == Object.class) {
            return Shape.RAW;
        }
        if (returned instanceof Class<?> type && type != Object.class && type != Map.class
                && type.getTypeParameters().length == 0 && !type.isPrimitive()) {
            try {
                AnyCallUtils.checkPayloadType(type, where + "'s response");
            } catch (IllegalArgumentException e) {
                throw new IllegalStateException(e.getMessage());
            }
            return Shape.TYPED;
        }
        throw new IllegalStateException(where + " returns " + returned.getTypeName() + "; it must return a "
            + "class with no type parameters (a model of payload types), Map<String, Object> for the response "
            + "as a map, or " + (async ? "Void" : "void") + (async ? "" : ", or a CompletableFuture of one of these"));
    }

    private static String name(String method, String where) {
        if (method == null || method.isBlank()) {
            throw new IllegalStateException(where + " names no remote method");
        }
        return method;
    }

    private static CallOptions options(Call call, Function<String, String> resolve, String where) {
        CallOptions options = CallOptions.DEFAULT;
        String timeout = resolve.apply(call.timeout()).trim();
        if (timeout.equalsIgnoreCase(NONE)) {
            options = options.withNoTimeout();
        } else if (!timeout.isEmpty()) {
            Duration duration;
            try {
                duration = DurationStyle.detectAndParse(timeout);
            } catch (IllegalArgumentException e) {
                throw new IllegalStateException(where + " has timeout '" + timeout + "'; use a duration such as "
                    + "2s, 500ms or PT30S, or none", e);
            }
            if (duration.isZero() || duration.isNegative()) {
                throw new IllegalStateException(where + " has timeout '" + timeout + "'; it must be positive, "
                    + "or none");
            }
            options = options.withTimeout(duration);
        }
        String depth = resolve.apply(call.maxQueueDepth()).trim();
        if (depth.equalsIgnoreCase(NONE)) {
            options = options.withNoQueueLimit();
        } else if (!depth.isEmpty()) {
            long limit;
            try {
                limit = Long.parseLong(depth);
            } catch (NumberFormatException e) {
                throw new IllegalStateException(where + " has maxQueueDepth '" + depth + "'; use a positive "
                    + "number, or none", e);
            }
            if (limit < 1) {
                throw new IllegalStateException(where + " has maxQueueDepth '" + depth + "'; it must be at "
                    + "least 1, or none");
            }
            options = options.withMaxQueueDepth(limit);
        }
        return options;
    }

    @Override
    public Object invoke(Object proxy, Method method, Object[] args) throws Throwable {
        if (method.getDeclaringClass() == Object.class) {
            return switch (method.getName()) {
                case "equals" -> proxy == args[0];
                case "hashCode" -> System.identityHashCode(proxy);
                case "toString" -> "AnyCallApi(" + apiInterface.getName() + ")";
                default -> throw new UnsupportedOperationException(method.getName());
            };
        }
        if (method.isDefault()) {
            return InvocationHandler.invokeDefault(proxy, method, args);
        }
        RemoteCall call = calls.get(method);
        AnyCallClient anyCall = client;
        Object request = args == null || args.length == 0 ? null : args[0];
        if (call.async()) {
            return switch (call.shape()) {
                case TYPED -> anyCall.async().call(call.method(), request, call.responseType(), call.options());
                case RAW -> anyCall.async().rawCall(call.method(), request, call.options());
                case DROPPED -> anyCall.async().rawCall(call.method(), request, call.options()).thenApply(r -> null);
            };
        }
        return switch (call.shape()) {
            case TYPED -> anyCall.call(call.method(), request, call.responseType(), call.options());
            case RAW -> anyCall.rawCall(call.method(), request, call.options());
            case DROPPED -> {
                anyCall.rawCall(call.method(), request, call.options());
                yield null;
            }
        };
    }
}
