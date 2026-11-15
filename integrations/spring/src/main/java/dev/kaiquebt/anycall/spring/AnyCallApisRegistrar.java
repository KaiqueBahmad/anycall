package dev.kaiquebt.anycall.spring;

import org.springframework.beans.factory.BeanClassLoaderAware;
import org.springframework.beans.factory.FactoryBean;
import org.springframework.beans.factory.annotation.AnnotatedBeanDefinition;
import org.springframework.beans.factory.config.BeanDefinition;
import org.springframework.beans.factory.support.AbstractBeanDefinition;
import org.springframework.beans.factory.support.BeanDefinitionBuilder;
import org.springframework.beans.factory.support.BeanDefinitionRegistry;
import org.springframework.context.annotation.ClassPathScanningCandidateComponentProvider;
import org.springframework.context.annotation.ImportBeanDefinitionRegistrar;
import org.springframework.core.annotation.AnnotationAttributes;
import org.springframework.core.type.AnnotationMetadata;
import org.springframework.core.type.filter.AnnotationTypeFilter;
import org.springframework.util.ClassUtils;

import java.util.ArrayList;
import java.util.Collection;
import java.util.List;

/**
 * Registers a bean for every {@link AnyCallApi} interface in the packages {@link EnableAnyCallApis}
 * names. Each is named after its interface; one already registered is left as it is.
 */
public class AnyCallApisRegistrar implements ImportBeanDefinitionRegistrar, BeanClassLoaderAware {

    private ClassLoader classLoader;

    @Override
    public void setBeanClassLoader(ClassLoader classLoader) {
        this.classLoader = classLoader;
    }

    @Override
    public void registerBeanDefinitions(AnnotationMetadata metadata, BeanDefinitionRegistry registry) {
        AnnotationAttributes attributes = AnnotationAttributes.fromMap(
            metadata.getAnnotationAttributes(EnableAnyCallApis.class.getName()));
        List<String> packages = new ArrayList<>();
        if (attributes != null) {
            packages.addAll(List.of(attributes.getStringArray("basePackages")));
            for (Class<?> type : attributes.getClassArray("basePackageClasses")) {
                packages.add(ClassUtils.getPackageName(type));
            }
        }
        if (packages.isEmpty()) {
            packages.add(ClassUtils.getPackageName(metadata.getClassName()));
        }
        register(packages, registry, classLoader);
    }

    /**
     * Registers a bean for every {@link AnyCallApi} interface in {@code packages}, loaded with
     * the context's {@code classLoader}.
     */
    static void register(Collection<String> packages, BeanDefinitionRegistry registry, ClassLoader classLoader) {
        ClassPathScanningCandidateComponentProvider scanner = new ClassPathScanningCandidateComponentProvider(false) {
            @Override
            protected boolean isCandidateComponent(AnnotatedBeanDefinition definition) {
                return definition.getMetadata().isInterface() && definition.getMetadata().isIndependent();
            }
        };
        scanner.addIncludeFilter(new AnnotationTypeFilter(AnyCallApi.class));
        for (String basePackage : packages) {
            for (BeanDefinition candidate : scanner.findCandidateComponents(basePackage)) {
                String interfaceName = candidate.getBeanClassName();
                if (registry.containsBeanDefinition(interfaceName)) {
                    continue;
                }
                Class<?> apiInterface = ClassUtils.resolveClassName(interfaceName, classLoader);
                AbstractBeanDefinition definition = BeanDefinitionBuilder
                    .genericBeanDefinition(AnyCallApiFactoryBean.class)
                    .addConstructorArgValue(apiInterface)
                    .getBeanDefinition();
                definition.setAttribute(FactoryBean.OBJECT_TYPE_ATTRIBUTE, apiInterface);
                registry.registerBeanDefinition(interfaceName, definition);
            }
        }
    }
}
