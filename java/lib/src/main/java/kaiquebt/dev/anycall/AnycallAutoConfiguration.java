package kaiquebt.dev.anycall;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.AutoConfiguration;
import org.springframework.context.annotation.ComponentScan;

@AutoConfiguration
@ComponentScan(basePackages = "dev.kaiquebt.anycall")
public class AnycallAutoConfiguration {

	public static void main(String[] args) {
		SpringApplication.run(AnycallAutoConfiguration.class, args);
	}

}
