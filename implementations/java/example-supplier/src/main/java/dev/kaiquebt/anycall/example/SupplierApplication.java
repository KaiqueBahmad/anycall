package dev.kaiquebt.anycall.example;

import dev.kaiquebt.anycall.core.AnyCall;
import dev.kaiquebt.anycall.core.AnyCallServer;
import dev.kaiquebt.anycall.example.supplier.SentimentAnalyzer;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;

public class SupplierApplication {
    private static final Logger logger = LoggerFactory.getLogger(SupplierApplication.class);

    public static void main(String[] args) throws Exception {
        logger.info("Supplier is initializing.");
        String redisUri = System.getenv("REDIS_URI");
        if (redisUri == null) {
            redisUri = "redis://localhost:16379";
        }

        SentimentAnalyzer analyzer = new SentimentAnalyzer();

        AnyCallServer server = AnyCall.server(redisUri);
        server.register(analyzer);
        server.start();

        writeHealthFile();

        Runtime.getRuntime().addShutdownHook(new Thread(() -> {
            logger.info("Shutting down supplier...");
            server.stop();
            deleteHealthFile();
        }));

        logger.info("Application ready. Supplier listening on queues.");

        Thread.currentThread().join();
    }

    private static final Path HEALTH_FILE = resolveHealthFilePath();

    private static Path resolveHealthFilePath() {
        String runtimeDir = System.getenv().getOrDefault("XDG_RUNTIME_DIR", "/tmp");
        return Paths.get(runtimeDir, "anycall", "health");
    }

    private static void writeHealthFile() {
        try {
            Files.createDirectories(HEALTH_FILE.getParent());
            Files.writeString(HEALTH_FILE, "OK");
            logger.info("Health file written to {}", HEALTH_FILE);
        } catch (Exception e) {
            logger.error("Failed to write health file", e);
        }
    }

    private static void deleteHealthFile() {
        try {
            if (Files.exists(HEALTH_FILE)) {
                Files.delete(HEALTH_FILE);
                logger.info("Health file removed: {}", HEALTH_FILE);
            }
        } catch (Exception e) {
            logger.error("Failed to remove health file", e);
        }
    }
}
