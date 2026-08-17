package dev.kaiquebt.anycall.example;

import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import dev.kaiquebt.anycall.core.AnyCall;
import dev.kaiquebt.anycall.core.AnyCallClient;
import dev.kaiquebt.anycall.example.model.TextRequest;
import dev.kaiquebt.anycall.example.model.Sentiment;

public class ConsumerApplication {
    private static final Logger logger = LoggerFactory.getLogger(ConsumerApplication.class);
    private static final int CONCURRENCY = 1;

    public static void main(String[] args) {
        ExecutorService executor = Executors.newFixedThreadPool(CONCURRENCY);
        try {
            logger.info("Consumer is initializing");
            String redisUri = System.getenv("REDIS_URI");
            if (redisUri == null) {
                redisUri = "redis://localhost:16379";
            }
            AnyCallClient anyCall = AnyCall.client(redisUri, true);

            CountDownLatch startGate = new CountDownLatch(1);
            CountDownLatch doneGate = new CountDownLatch(CONCURRENCY);

            for (int i = 1; i <= CONCURRENCY; i++) {
                final int id = i;
                executor.submit(() -> {
                    try {
                        startGate.await();
                        TextRequest request = new TextRequest("Hello, AnyCall! #" + id);
                        logger.info("[Consumer #{}] Calling analyze-sentiment with: {}", id, request.text());
                        long t0 = System.nanoTime();
                        Sentiment response = anyCall.call("analyze-sentiment", request, Sentiment.class);
                        long ms = (System.nanoTime() - t0) / 1_000_000;
                        logger.info("[Consumer #{}] Response in {} ms: {}", id, ms, response);
                    } catch (InterruptedException e) {
                        Thread.currentThread().interrupt();
                    } catch (Exception e) {
                        logger.error("[Consumer #{}] Failed", id, e);
                    } finally {
                        doneGate.countDown();
                    }
                });
            }

            long start = System.nanoTime();
            startGate.countDown();
            doneGate.await();
            logger.info("All {} calls finished in {} ms", CONCURRENCY, (System.nanoTime() - start) / 1_000_000);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
        } finally {
            executor.shutdown();
            try {
                executor.awaitTermination(5, TimeUnit.SECONDS);
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
            }
            System.exit(0);
        }
    }
}
