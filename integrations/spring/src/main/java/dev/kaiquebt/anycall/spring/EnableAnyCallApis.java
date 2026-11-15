package dev.kaiquebt.anycall.spring;

import org.springframework.context.annotation.Import;

import java.lang.annotation.Documented;
import java.lang.annotation.ElementType;
import java.lang.annotation.Retention;
import java.lang.annotation.RetentionPolicy;
import java.lang.annotation.Target;

/**
 * Looks for {@link AnyCallApi} interfaces in the given packages. Needed only for interfaces
 * outside the application's own packages, which are looked in already.
 */
@Target(ElementType.TYPE)
@Retention(RetentionPolicy.RUNTIME)
@Documented
@Import(AnyCallApisRegistrar.class)
public @interface EnableAnyCallApis {

    /** Packages to look in. */
    String[] basePackages() default {};

    /** Packages to look in, named by a class in each. */
    Class<?>[] basePackageClasses() default {};
}
