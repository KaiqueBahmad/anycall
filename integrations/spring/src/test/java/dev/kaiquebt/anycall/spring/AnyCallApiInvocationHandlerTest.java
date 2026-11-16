package dev.kaiquebt.anycall.spring;

import dev.kaiquebt.anycall.core.AnyCallClient;
import dev.kaiquebt.anycall.core.AsyncCalls;
import dev.kaiquebt.anycall.core.CallOptions;
import dev.kaiquebt.anycall.spring.apis.SentimentApi;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;

import java.time.Duration;
import java.util.List;
import java.util.Map;
import java.util.concurrent.CompletableFuture;
import java.util.function.Function;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class AnyCallApiInvocationHandlerTest {

    private final AnyCallClient client = mock(AnyCallClient.class);
    private final AsyncCalls async = mock(AsyncCalls.class);
    private final Map<String, Object> request = Map.of("text", "bom");

    /** Placeholders resolve to their defaults, as with no property set. */
    private static final Function<String, String> DEFAULTS =
        value -> value.replaceAll("\\$\\{[^:}]*:([^}]*)}", "$1");

    private <T> T api(Class<T> type) {
        return AnyCallApiFactoryBean.create(type, client, DEFAULTS);
    }

    private <T> T api(Class<T> type, Function<String, String> resolve) {
        return AnyCallApiFactoryBean.create(type, client, resolve);
    }

    private CallOptions optionsOfTypedCall(Class<?> responseType) {
        ArgumentCaptor<CallOptions> options = ArgumentCaptor.forClass(CallOptions.class);
        verify(client).call(eq("analyze-sentiment"), eq(request), eq(responseType), options.capture());
        return options.getValue();
    }

    @Test
    void aModelReturnIsATypedCallWithTheClientsSettings() {
        when(client.call(eq("analyze-sentiment"), eq(request), eq(SentimentApi.Sentiment.class), any(CallOptions.class)))
            .thenReturn(new SentimentApi.Sentiment("positive"));

        assertThat(api(SentimentApi.class).analyze(request)).isEqualTo(new SentimentApi.Sentiment("positive"));

        CallOptions options = optionsOfTypedCall(SentimentApi.Sentiment.class);
        assertThat(options.timeoutOr(Duration.ofDays(1))).isEqualTo(Duration.ofDays(1));
        assertThat(options.maxQueueDepthOr(7L)).isEqualTo(7L);
    }

    @Test
    void aFutureOfAModelIsATypedCallWithoutWaiting() {
        when(client.async()).thenReturn(async);
        when(async.call(eq("analyze-sentiment"), eq(request), eq(SentimentApi.Sentiment.class), any(CallOptions.class)))
            .thenReturn(CompletableFuture.completedFuture(new SentimentApi.Sentiment("ok")));

        assertThat(api(SentimentApi.class).analyzeAsync(request).join()).isEqualTo(new SentimentApi.Sentiment("ok"));

        ArgumentCaptor<CallOptions> options = ArgumentCaptor.forClass(CallOptions.class);
        verify(async).call(eq("analyze-sentiment"), eq(request), eq(SentimentApi.Sentiment.class), options.capture());
        assertThat(options.getValue().timeoutOr(null)).isEqualTo(Duration.ofSeconds(2));
        assertThat(options.getValue().maxQueueDepthOr(7L)).isNull();
    }

    @Test
    void aMapOfStringToObjectIsARawCall() {
        when(client.rawCall(eq("analyze-sentiment"), eq(request), any(CallOptions.class))).thenReturn(Map.of("label", "x"));
        when(client.async()).thenReturn(async);
        when(async.rawCall(eq("analyze-sentiment"), eq(request), any(CallOptions.class)))
            .thenReturn(CompletableFuture.completedFuture(Map.of("label", "y")));

        assertThat(api(SentimentApi.class).analyzeRaw(request)).containsEntry("label", "x");
        assertThat(api(SentimentApi.class).analyzeRawAsync(request).join()).containsEntry("label", "y");
    }

    @Test
    void voidWaitsAndDropsTheResponse() {
        when(client.async()).thenReturn(async);
        when(async.rawCall(eq("log"), eq(request), any(CallOptions.class)))
            .thenReturn(CompletableFuture.completedFuture(Map.of("ignored", true)));

        api(SentimentApi.class).log(request);
        assertThat(api(SentimentApi.class).logAsync(request).join()).isNull();

        verify(client).rawCall(eq("log"), eq(request), any(CallOptions.class));
    }

    @Test
    void settingsMayComeFromConfiguration() {
        when(client.call(eq("analyze-sentiment"), eq(request), eq(SentimentApi.Sentiment.class), any(CallOptions.class)))
            .thenReturn(new SentimentApi.Sentiment("positive"));

        api(SentimentApi.class).analyzeConfigured(request);

        CallOptions options = optionsOfTypedCall(SentimentApi.Sentiment.class);
        assertThat(options.timeoutOr(null)).isEqualTo(Duration.ofSeconds(3));
        assertThat(options.maxQueueDepthOr(7L)).isNull();
    }

    interface Pings {
        @Call("ping")
        String ping();
    }

    @Test
    void aMethodWithNoArgumentSendsANullRequest() {
        when(client.call(eq("ping"), eq(null), eq(String.class), any(CallOptions.class))).thenReturn("pong");

        assertThat(api(Pings.class).ping()).isEqualTo("pong");
    }

    interface WithStatic {
        @Call("ping")
        String ping();

        static String describe() {
            return "pings";
        }
    }

    @Test
    void staticMethodsAreLeftAlone() {
        when(client.call(eq("ping"), eq(null), eq(String.class), any(CallOptions.class))).thenReturn("pong");

        assertThat(api(WithStatic.class).ping()).isEqualTo("pong");
        assertThat(WithStatic.describe()).isEqualTo("pings");
    }

    @Test
    void defaultMethodsRunAsWritten() {
        when(client.call(eq("analyze-sentiment"), eq(request), eq(SentimentApi.Sentiment.class), any(CallOptions.class)))
            .thenReturn(new SentimentApi.Sentiment("positive"));

        assertThat(api(SentimentApi.class).labelOf(request)).isEqualTo("positive");
    }

    @Test
    void objectMethodsDontCall() {
        SentimentApi api = api(SentimentApi.class);
        assertThat(api.toString()).contains("SentimentApi");
        assertThat(api).isEqualTo(api);
        assertThat(api.hashCode()).isEqualTo(System.identityHashCode(api));
    }

    interface NoCall { String missing(Object request); }

    interface TwoArguments { @Call("x") String two(Object a, Object b); }

    interface RawFuture {
        @Call("x")
        @SuppressWarnings("rawtypes")
        CompletableFuture raw(Object request);
    }

    interface ReturnsObject { @Call("x") Object any(Object request); }

    interface ReturnsList { @Call("x") List<String> list(Object request); }

    interface ReturnsOtherMap { @Call("x") Map<String, Integer> map(Object request); }

    interface ReturnsJsonNode { @Call("x") com.fasterxml.jackson.databind.JsonNode tree(Object request); }

    record Logged(java.time.Instant at) { }

    interface ReturnsInstantModel { @Call("x") CompletableFuture<Logged> logged(Object request); }

    interface ReturnsVoidFutureOfVoid { @Call("x") CompletableFuture<Object> future(Object request); }

    private void failsWith(Class<?> type, String message) {
        assertThatThrownBy(() -> api(type)).isInstanceOf(IllegalStateException.class).hasMessageContaining(message);
    }

    @Test
    void mistakesInTheInterfaceFailWhenTheProxyIsMade() {
        failsWith(NoCall.class, "no @Call");
        failsWith(TwoArguments.class, "at most one argument");
        failsWith(RawFuture.class, "raw CompletableFuture");
        failsWith(ReturnsObject.class, "returns java.lang.Object");
        failsWith(ReturnsList.class, "returns java.util.List<java.lang.String>");
        failsWith(ReturnsOtherMap.class, "returns java.util.Map<java.lang.String, java.lang.Integer>");
        failsWith(ReturnsVoidFutureOfVoid.class, "returns java.lang.Object");
        failsWith(ReturnsJsonNode.class, "tree's response is JsonNode, not an AnyCall payload type");
        failsWith(ReturnsInstantModel.class, "logged's response: Logged.at is Instant, not an AnyCall payload type");
    }

    interface Configured {
        @Call(value = "x", timeout = "T", maxQueueDepth = "D")
        String configured(Object request);
    }

    private CallOptions configured(String timeout, String depth) {
        when(client.call(eq("x"), eq(request), eq(String.class), any(CallOptions.class))).thenReturn("ok");
        api(Configured.class, value -> value.equals("T") ? timeout : value.equals("D") ? depth : value)
            .configured(request);
        ArgumentCaptor<CallOptions> options = ArgumentCaptor.forClass(CallOptions.class);
        verify(client).call(eq("x"), eq(request), eq(String.class), options.capture());
        return options.getValue();
    }

    @Test
    void durationsAndLimitsAreRead() {
        CallOptions options = configured("500ms", "50");
        assertThat(options.timeoutOr(null)).isEqualTo(Duration.ofMillis(500));
        assertThat(options.maxQueueDepthOr(null)).isEqualTo(50L);
    }

    @Test
    void noneLiftsTheLimitAndEmptyKeepsTheClients() {
        CallOptions options = configured("none", "");
        assertThat(options.timeoutOr(Duration.ofDays(1))).isNull();
        assertThat(options.maxQueueDepthOr(7L)).isEqualTo(7L);
    }

    private void configuredFails(String timeout, String depth, String message) {
        assertThatThrownBy(() -> api(Configured.class,
                value -> value.equals("T") ? timeout : value.equals("D") ? depth : value))
            .isInstanceOf(IllegalStateException.class).hasMessageContaining(message);
    }

    interface WithSpel {
        @Call(value = "x", timeout = "#{2 * 1000}ms")
        String spel(Object request);
    }

    @Test
    void spelIsNotRead() {
        failsWith(WithSpel.class, "not SpEL");
    }

    @Test
    void valuesThatArentValidFailWhenTheProxyIsMade() {
        configuredFails("two seconds", "", "timeout 'two seconds'");
        configuredFails("0s", "", "must be positive");
        configuredFails("", "lots", "maxQueueDepth 'lots'");
        configuredFails("", "0", "at least 1");
    }
}
