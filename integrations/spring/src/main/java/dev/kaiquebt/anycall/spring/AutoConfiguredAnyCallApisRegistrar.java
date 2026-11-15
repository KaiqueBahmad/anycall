package dev.kaiquebt.anycall.spring;

import org.springframework.beans.factory.BeanClassLoaderAware;
import org.springframework.beans.factory.BeanFactory;
import org.springframework.beans.factory.BeanFactoryAware;
import org.springframework.beans.factory.support.BeanDefinitionRegistry;
import org.springframework.boot.autoconfigure.AutoConfigurationPackages;
import org.springframework.context.annotation.ImportBeanDefinitionRegistrar;
import org.springframework.core.type.AnnotationMetadata;

/** Registers the {@link AnyCallApi} interfaces of the application's own packages. */
class AutoConfiguredAnyCallApisRegistrar implements ImportBeanDefinitionRegistrar, BeanFactoryAware,
        BeanClassLoaderAware {

    private BeanFactory beanFactory;
    private ClassLoader classLoader;

    @Override
    public void setBeanClassLoader(ClassLoader classLoader) {
        this.classLoader = classLoader;
    }

    @Override
    public void setBeanFactory(BeanFactory beanFactory) {
        this.beanFactory = beanFactory;
    }

    @Override
    public void registerBeanDefinitions(AnnotationMetadata metadata, BeanDefinitionRegistry registry) {
        if (AutoConfigurationPackages.has(beanFactory)) {
            AnyCallApisRegistrar.register(AutoConfigurationPackages.get(beanFactory), registry, classLoader);
        }
    }
}
