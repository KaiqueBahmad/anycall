package dev.kaiquebt.anycall.spring.apis;

import dev.kaiquebt.anycall.spring.AnyCallApi;
import dev.kaiquebt.anycall.spring.Call;

import java.util.Map;
import java.util.concurrent.CompletableFuture;

@AnyCallApi
public interface SentimentApi {

    record Sentiment(String label) {
    }

    @Call("analyze-sentiment")
    Sentiment analyze(Map<String, Object> request);

    @Call(value = "analyze-sentiment", timeout = "2s", maxQueueDepth = "none")
    CompletableFuture<Sentiment> analyzeAsync(Map<String, Object> request);

    @Call("analyze-sentiment")
    Map<String, Object> analyzeRaw(Map<String, Object> request);

    @Call("analyze-sentiment")
    CompletableFuture<Map<String, Object>> analyzeRawAsync(Map<String, Object> request);

    @Call("log")
    void log(Map<String, Object> request);

    @Call("log")
    CompletableFuture<Void> logAsync(Map<String, Object> request);

    @Call(value = "${sentiment.method:analyze-sentiment}",
          timeout = "${sentiment.timeout:3s}", maxQueueDepth = "${sentiment.max-queue:none}")
    Sentiment analyzeConfigured(Map<String, Object> request);

    default String labelOf(Map<String, Object> request) {
        return analyze(request).label();
    }
}
