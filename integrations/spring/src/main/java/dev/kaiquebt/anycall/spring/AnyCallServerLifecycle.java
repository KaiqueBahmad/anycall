package dev.kaiquebt.anycall.spring;

import dev.kaiquebt.anycall.annotation.Supply;
import dev.kaiquebt.anycall.core.AnyCallServer;
import dev.kaiquebt.anycall.core.AnyCallSupplier;
import dev.kaiquebt.anycall.core.AnycallUtils;
import dev.kaiquebt.anycall.core.SupplyHandler;
import org.apache.commons.logging.Log;
import org.apache.commons.logging.LogFactory;
import org.springframework.aop.framework.AopProxyUtils;
import org.springframework.aop.support.AopUtils;
import org.springframework.context.ApplicationContext;
import org.springframework.context.SmartLifecycle;
import org.springframework.util.ReflectionUtils;

import java.lang.reflect.InvocationTargetException;
import java.lang.reflect.Method;
import java.lang.reflect.Modifier;
import java.time.Duration;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * Serves every {@code @AnyCallSupplier} bean of the context once it has started, and stops
 * the server when the context closes: a stop finishes the requests already taken, for up to
 * the shutdown timeout. Past it, the handlers still running are interrupted and the close goes
 * on: one that stops on the interrupt fails its call, one that ignores it no longer holds the
 * close up.
 * <p>
 * Each {@code @Supply} method is read from the bean's own class, since a Spring proxy's class
 * doesn't carry the annotations, and called through the bean Spring hands out, so the
 * proxy's advice ({@code @Transactional}, {@code @Timed}, security) runs as for any other
 * call. A proxy can't call a private or final method that way, so one fails the start. Two beans supplying the same method name fail the
 * start: which one would serve it would depend on the order beans come in.
 */
public class AnyCallServerLifecycle implements SmartLifecycle {

    private static final Log log = LogFactory.getLog(AnyCallServerLifecycle.class);

    private final AnyCallServer server;
    private final ApplicationContext context;
    private final Duration shutdownTimeout;
    private volatile boolean running;

    public AnyCallServerLifecycle(AnyCallServer server, ApplicationContext context, Duration shutdownTimeout) {
        this.server = server;
        this.context = context;
        this.shutdownTimeout = shutdownTimeout;
    }

    @Override
    public void start() {
        Map<String, Object> beans = new LinkedHashMap<>();
        Map<String, List<String>> beansOfMethod = new LinkedHashMap<>();
        for (Map.Entry<String, Object> entry : context.getBeansWithAnnotation(AnyCallSupplier.class).entrySet()) {
            String beanName = entry.getKey();
            Object bean = entry.getValue();
            for (String method : AnycallUtils.methods(declaring(bean))) {
                beansOfMethod.computeIfAbsent(method, m -> new ArrayList<>()).add(beanName);
            }
            beans.put(beanName, bean);
        }

        List<String> duplicates = new ArrayList<>();
        for (Map.Entry<String, List<String>> entry : beansOfMethod.entrySet()) {
            if (entry.getValue().size() > 1) {
                duplicates.add("'" + entry.getKey() + "' by " + String.join(", ", entry.getValue()));
            }
        }
        if (!duplicates.isEmpty()) {
            throw new IllegalStateException("AnyCall methods supplied by more than one bean, where only one may: "
                + String.join("; ", duplicates));
        }

        beans.forEach(this::registerThroughBean);
        server.start();
        running = true;
    }

    /** The object whose class declares the bean's {@code @Supply} methods: a proxy's target. */
    private static Object declaring(Object bean) {
        Object target = AopProxyUtils.getSingletonTarget(bean);
        return target != null ? target : bean;
    }

    private void registerThroughBean(String beanName, Object bean) {
        Object declaring = declaring(bean);
        for (Method method : declaring.getClass().getDeclaredMethods()) {
            Supply supply = method.getAnnotation(Supply.class);
            if (supply == null) {
                continue;
            }
            Method invocable;
            try {
                invocable = AopUtils.selectInvocableMethod(method, bean.getClass());
            } catch (IllegalStateException e) {
                throw new IllegalStateException("Bean '" + beanName + "': @Supply method " + method.getName()
                    + " can't be called through its proxy; make it public", e);
            }
            if (AopUtils.isAopProxy(bean) && Modifier.isFinal(invocable.getModifiers())) {
                throw new IllegalStateException("Bean '" + beanName + "': @Supply method " + method.getName()
                    + " is final, so its proxy can't call it; make it not final");
            }
            ReflectionUtils.makeAccessible(invocable);
            server.register(AnycallUtils.method(declaring, supply.methodName()), invoking(bean, invocable));
        }
    }

    /** Calls {@code method} on {@code bean}, throwing what the method throws. */
    private static SupplyHandler<Object, Object> invoking(Object bean, Method method) {
        return (ctx, request) -> {
            try {
                return method.invoke(bean, ctx, request);
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

    /**
     * Stops the server on a thread of its own, since a synchronous stop isn't covered by
     * Spring's shutdown-phase timeout, and interrupts it, which gives up on the requests still
     * running, if it takes longer than the shutdown timeout.
     */
    @Override
    public void stop() {
        Thread stopping = new Thread(server::stop, "anycall-server-stop");
        stopping.start();
        try {
            stopping.join(shutdownTimeout.toMillis());
            if (stopping.isAlive()) {
                log.warn("AnyCall server still had requests running after " + shutdownTimeout
                    + " (anycall.server.shutdown-timeout); giving up on them");
                stopping.interrupt();
                stopping.join();
            }
        } catch (InterruptedException e) {
            stopping.interrupt();
            Thread.currentThread().interrupt();
        }
        running = false;
    }

    @Override
    public boolean isRunning() {
        return running;
    }

    /** Starts after the rest of the context, and stops before it, so suppliers' dependencies are there. */
    @Override
    public int getPhase() {
        return Integer.MAX_VALUE - 100;
    }
}
