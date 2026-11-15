package dev.kaiquebt.anycall.spring;

import dev.kaiquebt.anycall.core.AnyCallClient;
import org.springframework.beans.factory.BeanFactory;
import org.springframework.beans.factory.BeanFactoryAware;
import org.springframework.beans.factory.NoSuchBeanDefinitionException;
import org.springframework.beans.factory.SmartFactoryBean;
import org.springframework.beans.factory.config.ConfigurableBeanFactory;

import java.lang.reflect.Proxy;
import java.util.function.Function;

/**
 * Makes the bean of one {@link AnyCallApi} interface: a proxy calling through the context's
 * client. It's made when the context starts, even if nothing injects it, so a mistake in the
 * interface, or a missing client, fails the start rather than a later call.
 */
public class AnyCallApiFactoryBean<T> implements SmartFactoryBean<T>, BeanFactoryAware {

    private final Class<T> apiInterface;
    private BeanFactory beanFactory;

    public AnyCallApiFactoryBean(Class<T> apiInterface) {
        this.apiInterface = apiInterface;
    }

    @Override
    public void setBeanFactory(BeanFactory beanFactory) {
        this.beanFactory = beanFactory;
    }

    @Override
    public T getObject() {
        AnyCallClient client;
        try {
            client = beanFactory.getBean(AnyCallClient.class);
        } catch (NoSuchBeanDefinitionException e) {
            throw new IllegalStateException(apiInterface.getName() + " needs an AnyCallClient bean and there's "
                + "none: set anycall.client.enabled to true, or define one", e);
        }
        return create(apiInterface, client, this::resolve);
    }

    @Override
    public boolean isEagerInit() {
        return true;
    }

    @Override
    public Class<T> getObjectType() {
        return apiInterface;
    }

    /**
     * Resolves the property placeholders of a {@link Call} attribute.
     *
     * @throws IllegalArgumentException if a placeholder has no value and no default
     */
    private String resolve(String value) {
        if (!(beanFactory instanceof ConfigurableBeanFactory factory)) {
            return value;
        }
        String resolved = factory.resolveEmbeddedValue(value);
        return resolved == null ? "" : resolved;
    }

    /**
     * A proxy of {@code apiInterface} whose calls go through {@code client}.
     *
     * @param resolve resolves a {@link Call} attribute
     * @throws IllegalStateException if a method of the interface isn't a valid remote call
     */
    static <T> T create(Class<T> apiInterface, AnyCallClient client, Function<String, String> resolve) {
        return apiInterface.cast(Proxy.newProxyInstance(apiInterface.getClassLoader(), new Class<?>[] {apiInterface},
            new AnyCallApiInvocationHandler(apiInterface, client, resolve)));
    }
}
