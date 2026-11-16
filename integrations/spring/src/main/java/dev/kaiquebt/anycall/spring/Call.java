package dev.kaiquebt.anycall.spring;

import java.lang.annotation.Documented;
import java.lang.annotation.ElementType;
import java.lang.annotation.Retention;
import java.lang.annotation.RetentionPolicy;
import java.lang.annotation.Target;

/**
 * A method of an {@link AnyCallApi} interface that calls the remote method {@link #value()}.
 * <p>
 * It takes one argument, the request, or none to send a {@code null} one. Its return type says
 * what the call returns:
 * <table>
 *   <caption>Return types</caption>
 *   <tr><th>Returns</th><th>Call</th></tr>
 *   <tr><td>{@code T}, a class of payload types</td><td>waits, and reads the response into {@code T}</td></tr>
 *   <tr><td>{@code Map<String, Object>}</td><td>a raw call: waits, and returns the response as a map</td></tr>
 *   <tr><td>{@code void}</td><td>waits, and drops the response</td></tr>
 *   <tr><td>{@code CompletableFuture<…>} of any of these</td><td>the same, without waiting ({@code Void} for void)</td></tr>
 * </table>
 * Anything else, such as {@code Object}, {@code List<Foo>} or a model with an {@code Instant},
 * fails the context at startup.
 * <p>
 * Every attribute may hold property placeholders ({@code ${...}}, with an optional default
 * after a colon), so a setting can be fixed or come from configuration:
 *
 * <pre>{@code
 * @Call(value = "analyze-sentiment", timeout = "2s")
 * Sentiment analyze(TextRequest request);
 *
 * @Call(value = "analyze-sentiment", timeout = "${sentiment.timeout:2s}", maxQueueDepth = "none")
 * Sentiment analyzeConfigured(TextRequest request);
 * }</pre>
 *
 * SpEL ({@code #{...}}) isn't read. Attributes are resolved once, when the context starts; a
 * value that doesn't resolve or isn't valid fails it. A setting left empty keeps the client's;
 * {@code "none"} lifts the limit.
 */
@Target(ElementType.METHOD)
@Retention(RetentionPolicy.RUNTIME)
@Documented
public @interface Call {

    /** The remote method's name. */
    String value();

    /**
     * How long the call waits for its response: a positive duration such as {@code "2s"},
     * {@code "500ms"} or {@code "PT30S"} (a bare number is milliseconds), or {@code "none"}.
     */
    String timeout() default "";

    /**
     * Reject the call if the method's queue already holds this many requests, at least 1, or
     * {@code "none"}.
     */
    String maxQueueDepth() default "";
}
