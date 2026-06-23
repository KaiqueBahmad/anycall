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
            redisUri = "redis://localhost:6379";
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

        logger.info("Application ready. Supplier listening on streams.");

        Thread.currentThread().join();
    }

    private static void writeHealthFile() {
        try {
            Path healthFile = Paths.get("/run/anycall/health");
            Files.createDirectories(healthFile.getParent());
            Files.writeString(healthFile, "OK");
            logger.info("Health file written to {}", healthFile);
        } catch (Exception e) {
            logger.error("Failed to write health file", e);
        }
    }

    private static void deleteHealthFile() {
        try {
            Path healthFile = Paths.get("/run/anycall/health");
            if (Files.exists(healthFile)) {
                Files.delete(healthFile);
                logger.info("Health file removed: {}", healthFile);
            }
        } catch (Exception e) {
            logger.error("Failed to remove health file", e);
        }
    }
}
