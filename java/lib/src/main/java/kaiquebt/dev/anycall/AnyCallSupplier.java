package kaiquebt.dev.anycall;

import org.springframework.stereotype.Component;

import java.lang.annotation.ElementType;
import java.lang.annotation.Retention;
import java.lang.annotation.RetentionPolicy;
import java.lang.annotation.Target;

/**
 * Marks a class as a supplier of AnyCall methods.
 * Classes annotated with this will be automatically scanned and registered
 * to handle remote calls via Redis.
 */
@Target(ElementType.TYPE)
@Retention(RetentionPolicy.RUNTIME)
@Component
public @interface AnyCallSupplier {
}
