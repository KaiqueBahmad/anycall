package kaiquebt.dev.anycall.example;

import org.springframework.boot.CommandLineRunner;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

@SpringBootApplication
public class SupplierApplication implements CommandLineRunner {

	public static void main(String[] args) {
		SpringApplication.run(SupplierApplication.class, args);
	}

	@Override
    public void run(String... args) throws Exception {
        // Keep alive
        Thread.currentThread().join();
    }

}
