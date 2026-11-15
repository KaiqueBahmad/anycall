package dev.kaiquebt.anycall.spring;

import java.lang.annotation.Documented;
import java.lang.annotation.ElementType;
import java.lang.annotation.Retention;
import java.lang.annotation.RetentionPolicy;
import java.lang.annotation.Target;

/**
 * Marks an interface whose methods call remote AnyCall methods, each a {@link Call}. It becomes
 * a bean that can be injected:
 *
 * <pre>{@code
 * @AnyCallApi
 * public interface SentimentApi {
 *     @Call("analyze-sentiment")
 *     Sentiment analyze(TextRequest request);
 *
 *     @Call(value = "analyze-sentiment", timeout = "2s")
 *     CompletableFuture<Sentiment> analyzeAsync(TextRequest request);
 * }
 * }</pre>
 *
 * Interfaces are found in the application's packages (those of its
 * {@code @SpringBootApplication}), or in the ones {@link EnableAnyCallApis} names.
 */
@Target(ElementType.TYPE)
@Retention(RetentionPolicy.RUNTIME)
@Documented
public @interface AnyCallApi {
}
