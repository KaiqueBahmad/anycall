package kaiquebt.dev.anycall.example;

import kaiquebt.dev.anycall.AnyCall;
import kaiquebt.dev.anycall.AnyCallServer;
import org.springframework.context.ApplicationContext;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

/**
 * Configuration class for AnyCall server.
 */
@Configuration
public class AnyCallConfiguration {

    @Bean
    public AnyCallServer anyCallServer(ApplicationContext applicationContext) {
        return AnyCall.server(applicationContext)
                      .group("product-workers")
                      .start();
    }
}
