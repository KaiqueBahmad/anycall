package dev.kaiquebt.anycall.annotation;

import java.lang.annotation.ElementType;
import java.lang.annotation.Retention;
import java.lang.annotation.RetentionPolicy;
import java.lang.annotation.Target;

/**
 * Marks a method as a remotely callable operation within an AnyCall supplier.
 * Methods annotated with {@code @Supply} are automatically registered to handle
 * remote procedure calls with the specified operation name via Redis.
 * Methods must have exactly two parameters — an {@link dev.kaiquebt.anycall.core.AnycallContext}
 * followed by the request type, which will be deserialized from the request payload —
 * and must have a return type that can be serialized to JSON.
 *
 * <p>Usage requirements:
 * <ul>
 *   <li>Must be used only on methods within a class annotated with {@code @AnyCallSupplier}</li>
 *   <li>Method must have exactly two parameters: {@code (AnycallContext, <request type>)}</li>
 *   <li>Method should not have a request parameter that cannot be deserialized from JSON</li>
 *   <li>Method return type must be serializable to JSON</li>
 * </ul>
 *
 * <p>Example:
 * <pre>
 * {@code
 * public class SentimentAnalyzer {
 *     @Supply("analyze-sentiment")
 *     public Sentiment analyzeSentiment(AnycallContext ctx, TextRequest req) {
 *         return new Sentiment(req.text(), "positive");
 *     }
 * }
 * }
 * </pre>
 *
 * @see dev.kaiquebt.anycall.core.AnyCallSupplier
 * @see dev.kaiquebt.anycall.core.AnycallContext
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

    /**
     * How many requests for this operation a single server instance may process at
     * the same time. Composes with scaling out via multiple server processes and with
     * the server-wide cap ({@code AnyCall.server(uri, metricsEnabled, maxConcurrency)}),
     * if set. Defaults to {@code 1} (one at a time per instance).
     *
     * @return the number of requests this method may process concurrently
     */
    int maxConcurrency() default 1;
}
