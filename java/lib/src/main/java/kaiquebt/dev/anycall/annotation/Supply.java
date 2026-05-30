package kaiquebt.dev.anycall.annotation;

import java.lang.annotation.ElementType;
import java.lang.annotation.Retention;
import java.lang.annotation.RetentionPolicy;
import java.lang.annotation.Target;

/**
 * Marks a method as a supplier of a specific AnyCall operation.
 * The method will be registered to handle remote calls with the specified name.
 *
 * Example:
 * <pre>
 * {@code
 * @Supply("create-new-product")
 * public Product createNewProduct(CreateProductRequest req) {
 *     return new Product(req.name(), req.priceInCents());
 * }
 * }
 * </pre>
 */
@Target(ElementType.METHOD)
@Retention(RetentionPolicy.RUNTIME)
public @interface Supply {
    /**
     * The name of the operation this method handles.
     */
    String value();
}
