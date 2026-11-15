package dev.kaiquebt.anycall.spring;

import dev.kaiquebt.anycall.core.AnyCall;
import org.springframework.beans.factory.support.BeanDefinitionRegistry;
import org.springframework.boot.autoconfigure.AutoConfiguration;
import org.springframework.context.annotation.Import;
import org.springframework.context.annotation.ImportBeanDefinitionRegistrar;
import org.springframework.core.type.AnnotationMetadata;

/**
 * Fails the context, before any AnyCall bean is made, when the {@code anycall} on the classpath
 * is of another contract ({@code X.Y}) than this module's, as when the application overrides
 * its version with one of another contract.
 */
@AutoConfiguration(before = AnyCallAutoConfiguration.class)
@Import(AnyCallContractAutoConfiguration.Check.class)
public class AnyCallContractAutoConfiguration {

    static class Check implements ImportBeanDefinitionRegistrar {

        @Override
        public void registerBeanDefinitions(AnnotationMetadata metadata, BeanDefinitionRegistry registry) {
            checkContract(Check.class.getPackage().getImplementationVersion(),
                AnyCall.class.getPackage().getImplementationVersion());
        }
    }

    /**
     * Throws if both are releases of different contracts. A version that's unknown, as when
     * running from classes rather than jars, or isn't {@code X.Y.Z}, as {@code 0-SNAPSHOT},
     * isn't checked.
     */
    static void checkContract(String springVersion, String anycallVersion) {
        String spring = contract(springVersion);
        String anycall = contract(anycallVersion);
        if (spring != null && anycall != null && !spring.equals(anycall)) {
            throw new IllegalStateException("anycall-spring " + springVersion + " is for contract " + spring
                + ", but anycall " + anycallVersion + " is of contract " + anycall + ": use anycall " + spring + ".x");
        }
    }

    /** The contract {@code X.Y} of a version {@code X.Y.Z}; null for anything else. */
    static String contract(String version) {
        String[] parts = version == null ? new String[0] : version.split("\\.");
        return parts.length == 3 ? parts[0] + "." + parts[1] : null;
    }
}
