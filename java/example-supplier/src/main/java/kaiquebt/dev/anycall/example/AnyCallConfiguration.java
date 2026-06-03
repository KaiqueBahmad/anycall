package kaiquebt.dev.anycall.example;

import kaiquebt.dev.anycall.core.AnyCall;
import kaiquebt.dev.anycall.core.AnyCallServer;
import kaiquebt.dev.anycall.core.RedisStreamAdapter;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

@Configuration
public class AnyCallConfiguration {

    @Bean
    public RedisStreamAdapter redisStreamAdapter() {
        System.out.println("AAAAAAAAAEIOU");
        System.out.println("redis://redis:6379");
        return new RedisStreamAdapter("redis://redis:6379");
    }

    @Bean
    public AnyCallServer anyCallServer(RedisStreamAdapter redis, ProductSupplier productSupplier) {
        return AnyCall.server(redis)
                      .register(productSupplier)
                      .group("product-workers")
                      .start();
    }
}
