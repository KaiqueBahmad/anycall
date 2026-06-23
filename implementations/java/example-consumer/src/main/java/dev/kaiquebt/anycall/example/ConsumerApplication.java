package dev.kaiquebt.anycall.example;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import dev.kaiquebt.anycall.core.AnyCall;
import dev.kaiquebt.anycall.core.AnyCallClient;
import dev.kaiquebt.anycall.example.model.TextRequest;
import dev.kaiquebt.anycall.example.model.Sentiment;

public class ConsumerApplication {
    private static final Logger logger = LoggerFactory.getLogger(ConsumerApplication.class);

    public static void main(String[] args) {
        try {
            logger.info("Consumer is initializing");

            String redisUri = System.getenv("REDIS_URI");
            if (redisUri == null) {
                redisUri = "redis://localhost:6379";
            }
            AnyCallClient anyCall = AnyCall.client(redisUri, true);

            TextRequest request = new TextRequest("Hello, AnyCall!");
            logger.info("[Consumer] Calling analyze-sentiment with: " + request.text());

            Sentiment response = anyCall.call("analyze-sentiment", request, Sentiment.class);
            logger.info("[Consumer] Response: " + response);
        } finally {
            System.exit(0);
        }
    }
}
