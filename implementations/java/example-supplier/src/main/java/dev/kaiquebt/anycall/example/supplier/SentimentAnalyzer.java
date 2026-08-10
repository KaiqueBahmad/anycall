package dev.kaiquebt.anycall.example.supplier;

import dev.kaiquebt.anycall.annotation.Supply;
import dev.kaiquebt.anycall.core.AnycallContext;
import dev.kaiquebt.anycall.example.model.Sentiment;
import dev.kaiquebt.anycall.example.model.TextRequest;

public class SentimentAnalyzer {

    @Supply(methodName = "analyze-sentiment")
    public Sentiment analyzeSentiment(AnycallContext ctx, TextRequest req) {
        return new Sentiment(req.text(), "positive");
    }
}
