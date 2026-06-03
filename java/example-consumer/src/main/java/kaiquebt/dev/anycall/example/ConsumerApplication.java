package kaiquebt.dev.anycall.example;

import kaiquebt.dev.anycall.client.AnyCallClientImpl;
import kaiquebt.dev.anycall.core.AnyCallClient;
import kaiquebt.dev.anycall.core.RedisStreamAdapter;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.boot.CommandLineRunner;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.context.annotation.Bean;
import org.springframework.stereotype.Component;

@SpringBootApplication
public class ConsumerApplication {

	public static void main(String[] args) {
		SpringApplication.run(ConsumerApplication.class, args);
	}

	@Bean
	public RedisStreamAdapter redisStreamAdapter() {
		return new RedisStreamAdapter("redis://redis:6379");
	}

	@Bean
	public AnyCallClient anyCallClient(RedisStreamAdapter redis) {
		return new AnyCallClientImpl(redis, new ObjectMapper());
	}

	@Component
	public static class ConsumerRunner implements CommandLineRunner {
		private final AnyCallClient anyCall;

		public ConsumerRunner(AnyCallClient anyCall) {
			this.anyCall = anyCall;
		}

		@Override
		public void run(String... args) throws Exception {
			try {
				System.out.println("[Consumer] Chamando supplier...");
				long startTime = System.currentTimeMillis();
				Product response = anyCall.call("create-new-product", new CreateProductRequest("teste", 123), Product.class);
				long endTime = System.currentTimeMillis();
				System.out.println("[Consumer] Resposta recebida em " + (endTime - startTime) + "ms");
				System.out.println("[Consumer] Produto: " + response);
			} catch (Exception e) {
				System.err.println("[Consumer] Erro ao chamar supplier: " + e.getMessage());
				e.printStackTrace();
			} finally {
				System.exit(0);
			}
		}
	}
}
