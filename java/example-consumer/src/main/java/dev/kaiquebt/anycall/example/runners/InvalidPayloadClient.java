package dev.kaiquebt.anycall.example.runners;

import dev.kaiquebt.anycall.core.AnyCall;
import dev.kaiquebt.anycall.core.AnyCallClient;
import dev.kaiquebt.anycall.example.model.Sentiment;
import dev.kaiquebt.anycall.exception.AnyCallError;

public class InvalidPayloadClient {

    private static record InvalidPayload(String notText, String other) {
    }

    public static void main(String[] args) {
        System.out.println("redis://localhost:6379");
        AnyCallClient client = AnyCall.client("redis://localhost:6379");
        client.call("analyze-sentiment", new InvalidPayload("aeiou", "tasd"), Sentiment.class);

        try {

        } catch (AnyCallError exc) {
            // if (exc instanceof RecoverableCall) {

            // }
        }

    }

}
