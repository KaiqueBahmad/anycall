package dev.kaiquebt.anycall.example.supplier;

import dev.kaiquebt.anycall.annotation.Supply;
import dev.kaiquebt.anycall.core.AnycallContext;
import dev.kaiquebt.anycall.example.model.Sentiment;
import dev.kaiquebt.anycall.example.model.TextRequest;

public class SentimentAnalyzer {

    @Supply(methodName = "analyze-sentiment", maxConcurrency = 1)
    public Sentiment analyzeSentiment(AnycallContext ctx, TextRequest req) {
        try {
            Thread.sleep(1000);
        } catch (InterruptedException e) {
            // TODO check if this is needed or can be raised to the anycall error handler
            Thread.currentThread().interrupt();
        }
        return new Sentiment(req.text(), "positive");
    }
}
