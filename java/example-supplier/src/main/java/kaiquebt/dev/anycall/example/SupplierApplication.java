package kaiquebt.dev.anycall.example;

import org.springframework.boot.CommandLineRunner;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.boot.context.event.ApplicationReadyEvent;
import org.springframework.context.event.EventListener;
import org.springframework.data.redis.core.RedisTemplate;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

@SpringBootApplication
public class SupplierApplication implements CommandLineRunner {
    private static final Logger logger = LoggerFactory.getLogger(SupplierApplication.class);
    private final RedisTemplate<String, String> redisTemplate;

    public SupplierApplication(RedisTemplate<String, String> redisTemplate) {
        this.redisTemplate = redisTemplate;
    }

	public static void main(String[] args) {
		SpringApplication.run(SupplierApplication.class, args);
	}

	@Override
    public void run(String... args) throws Exception {
        redisTemplate.opsForValue().get("ping"); // throws if Redis is down

        Path healthFile = Paths.get("/tmp/anycall/health");
        Files.createDirectories(healthFile.getParent());
        Files.writeString(healthFile, "OK");
        logger.info("Application ready. Health file written to {}", healthFile);

        Thread.currentThread().join();
    }

}
