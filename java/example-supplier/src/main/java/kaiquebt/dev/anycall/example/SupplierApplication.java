package kaiquebt.dev.anycall.example;

import kaiquebt.dev.anycall.core.AnyCall;
import kaiquebt.dev.anycall.core.AnyCallServer;
import kaiquebt.dev.anycall.core.RedisStreamAdapter;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;

public class SupplierApplication {
    private static final Logger logger = LoggerFactory.getLogger(SupplierApplication.class);

    public static void main(String[] args) throws Exception {
        String redisUri = System.getenv("REDIS_URI");
        if (redisUri == null) {
            redisUri = "redis://localhost:6379";
        }

        RedisStreamAdapter redis = new RedisStreamAdapter(redisUri);
        ProductSupplier supplier = new ProductSupplier();

        AnyCallServer server = AnyCall.server(redis)
            .register(supplier)
            .group("product-workers")
            .metrics(false)
            .start();

        writeHealthFile();
        logger.info("Application ready. Supplier listening on streams.");

        Thread.currentThread().join();
    }

    private static void writeHealthFile() throws Exception {
        Path healthFile = Paths.get("/tmp/anycall/health");
        Files.createDirectories(healthFile.getParent());
        Files.writeString(healthFile, "OK");
        logger.info("Health file written to {}", healthFile);
    }
}
