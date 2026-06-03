package kaiquebt.dev.anycall.annotation;

import java.lang.annotation.ElementType;
import java.lang.annotation.Retention;
import java.lang.annotation.RetentionPolicy;
import java.lang.annotation.Target;

/**
 * Marks a method as a remotely callable operation within an AnyCall supplier.
 * Methods annotated with {@code @Supply} are automatically registered to handle
 * remote procedure calls with the specified operation name via Redis.
 * Methods must have exactly one parameter which will be deserialized from the request payload,
 * and must have a return type that can be serialized to JSON.
 *
 * <p>Usage requirements:
 * <ul>
 *   <li>Must be used only on methods within a class annotated with {@code @AnyCallSupplier}</li>
 *   <li>Method must have exactly one parameter</li>
 *   <li>Method should not have parameters that cannot be deserialized from JSON</li>
 *   <li>Method return type must be serializable to JSON</li>
 * </ul>
 *
 * <p>Example:
 * <pre>
 * {@code
 * @AnyCallSupplier
 * public class ProductService {
 *     @Supply("create-new-product")
 *     public Product createNewProduct(CreateProductRequest req) {
 *         return new Product(req.name(), req.priceInCents());
 *     }
 * }
 * }
 * </pre>
 *
 * @see kaiquebt.dev.anycall.core.AnyCallSupplier
 */
@Target(ElementType.METHOD)
@Retention(RetentionPolicy.RUNTIME)
public @interface Supply {
    /**
     * The unique name of the operation this method handles.
     * This name is used by clients to identify and invoke this specific remote method.
     *
     * @return the operation name
     */
    String value();
}
