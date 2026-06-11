package dev.kaiquebt.anycall.example.supplier;

import dev.kaiquebt.anycall.annotation.Supply;
import dev.kaiquebt.anycall.example.model.Sentiment;
import dev.kaiquebt.anycall.example.model.TextRequest;

public class SentimentAnalyzer {

    @Supply("analyze-sentiment")
    public Sentiment analyzeSentiment(TextRequest req) {
        return new Sentiment(req.getText(), "positive");
    }
}
