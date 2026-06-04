package kaiquebt.dev.anycall.example;

import kaiquebt.dev.anycall.client.AnyCallClientImpl;
import kaiquebt.dev.anycall.core.AnyCallClient;
import kaiquebt.dev.anycall.core.RedisStreamAdapter;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.time.Duration;
import java.util.Arrays;

public class ConsumerApplication {

    public static void main(String[] args) {
        try {
            RedisStreamAdapter redisAdapter = new RedisStreamAdapter("redis://redis:6379");
            AnyCallClient anyCall = new AnyCallClientImpl(redisAdapter, new ObjectMapper(), Duration.ofSeconds(30), true);

            System.out.println("[Consumer] ---- Warmup Call ----");
            CreateProductRequest warmupRequest = new CreateProductRequest("warmup", 0);
            long warmupStart = System.nanoTime();
            try {
                Product warmupResponse = anyCall.call("create-new-product", warmupRequest, Product.class);
                long warmupElapsed = (System.nanoTime() - warmupStart) / 1_000_000;
                System.out.println("[Consumer] Warmup call succeeded in " + warmupElapsed + "ms");
                System.out.println("[Consumer] Response: " + warmupResponse);
            } catch (Exception e) {
                System.err.println("[Consumer] Warmup call failed: " + e.getMessage());
            }

            System.out.println("[Consumer]\n---- Load Test Loop ----");
            int total = 1;
            long[] timings = new long[total];
            int ok = 0;

            long suiteStart = System.currentTimeMillis();

            for (int i = 1; i <= total; i++) {
                CreateProductRequest request = new CreateProductRequest("test-" + i, 123 + i);

                try {
                    long startTime = System.nanoTime();
                    Product response = anyCall.call("create-new-product", request, Product.class);
                    long elapsed = (System.nanoTime() - startTime) / 1_000_000;

                    timings[ok] = elapsed;
                    ok++;
                    if (i % 10 == 0 || i == 1) {
                        System.out.println("[Consumer] Call " + i + "/" + total + " -> " + elapsed + "ms");
                    }
                } catch (Exception e) {
                    System.err.println("[Consumer] Error on call " + i + ": " + e.getMessage());
                }
            }

            long suiteElapsed = System.currentTimeMillis() - suiteStart;

            System.out.println("[Consumer] ---- Summary ----");
            System.out.println("[Consumer] Succeeded: " + ok + "/" + total);
            System.out.println("[Consumer] Total wall time: " + suiteElapsed + "ms");

            if (ok > 0) {
                long[] sorted = Arrays.copyOf(timings, ok);
                Arrays.sort(sorted);
                long sum = 0;
                for (long t : sorted)
                    sum += t;

                System.out.println("[Consumer] Min: " + sorted[0] + "ms");
                System.out.println("[Consumer] Avg: " + (sum / ok) + "ms");
                System.out.println("[Consumer] p50: " + sorted[(int) (ok * 0.50)] + "ms");
                System.out.println("[Consumer] p95: " + sorted[(int) Math.min(ok - 1, ok * 0.95)] + "ms");
                System.out.println("[Consumer] p99: " + sorted[(int) Math.min(ok - 1, ok * 0.99)] + "ms");
                System.out.println("[Consumer] Max: " + sorted[ok - 1] + "ms");
            }
        } finally {
            System.exit(0);
        }
    }
}
