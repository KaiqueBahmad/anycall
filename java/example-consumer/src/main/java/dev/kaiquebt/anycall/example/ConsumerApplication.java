package dev.kaiquebt.anycall.example;

import dev.kaiquebt.anycall.core.AnyCall;
import dev.kaiquebt.anycall.core.AnyCallClient;
import dev.kaiquebt.anycall.example.model.TextRequest;
import dev.kaiquebt.anycall.example.model.Sentiment;

public class ConsumerApplication {

    public static void main(String[] args) {
        try {
            String redisUri = System.getenv("REDIS_URI");
            if (redisUri == null) {
                redisUri = "redis://localhost:6379";
            }
            AnyCallClient anyCall = AnyCall.client(redisUri, true);

            TextRequest request = new TextRequest("Hello, AnyCall!");
            System.out.println("[Consumer] Calling analyze-sentiment with: " + request.text());

            Sentiment response = anyCall.call("analyze-sentiment", request, Sentiment.class);
            System.out.println("[Consumer] Response: " + response);
        } finally {
            System.exit(0);
        }
    }
}
