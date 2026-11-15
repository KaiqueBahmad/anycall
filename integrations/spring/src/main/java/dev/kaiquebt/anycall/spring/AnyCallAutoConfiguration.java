package dev.kaiquebt.anycall.spring;

import dev.kaiquebt.anycall.core.AnyCall;
import dev.kaiquebt.anycall.core.AnyCallClient;
import dev.kaiquebt.anycall.core.AnyCallServer;
import dev.kaiquebt.anycall.core.AnyCallSupplier;
import dev.kaiquebt.anycall.core.CallOptions;
import dev.kaiquebt.anycall.core.ServerOptions;
import org.apache.commons.logging.Log;
import org.apache.commons.logging.LogFactory;
import org.springframework.beans.factory.SmartInitializingSingleton;
import org.springframework.boot.autoconfigure.AutoConfiguration;
import org.springframework.boot.autoconfigure.condition.ConditionalOnBean;
import org.springframework.boot.autoconfigure.condition.ConditionalOnMissingBean;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.context.ApplicationContext;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Import;

/**
 * An {@link AnyCallClient} bean, an {@link AnyCallServer} that serves the context's
 * {@code @AnyCallSupplier} beans, both from {@link AnyCallProperties}, and a bean for every
 * {@link AnyCallApi} interface in the application's packages. The client and server back off
 * when the application defines its own.
 */
@AutoConfiguration
@EnableConfigurationProperties(AnyCallProperties.class)
@Import(AutoConfiguredAnyCallApisRegistrar.class)
public class AnyCallAutoConfiguration {

    private static final Log log = LogFactory.getLog(AnyCallAutoConfiguration.class);

    @Bean(destroyMethod = "close")
    @ConditionalOnMissingBean
    @ConditionalOnProperty(prefix = "anycall.client", name = "enabled", matchIfMissing = true)
    public AnyCallClient anyCallClient(AnyCallProperties properties) {
        return AnyCall.client(properties.getRedisUrl(), properties.getPrefix(), callDefaults(properties.getClient()));
    }

    @Bean
    @ConditionalOnMissingBean
    @ConditionalOnBean(annotation = AnyCallSupplier.class)
    @ConditionalOnProperty(prefix = "anycall.server", name = "enabled", matchIfMissing = true)
    public AnyCallServer anyCallServer(AnyCallProperties properties) {
        Integer maxConcurrency = properties.getServer().getMaxConcurrency();
        ServerOptions options = maxConcurrency == null
            ? ServerOptions.DEFAULT : ServerOptions.DEFAULT.withMaxConcurrency(maxConcurrency);
        return AnyCall.server(properties.getRedisUrl(), properties.getPrefix(), options);
    }

    @Bean
    @ConditionalOnBean(AnyCallServer.class)
    @ConditionalOnMissingBean
    public AnyCallServerLifecycle anyCallServerLifecycle(AnyCallServer server, ApplicationContext context,
                                                         AnyCallProperties properties) {
        return new AnyCallServerLifecycle(server, context, properties.getServer().getShutdownTimeout());
    }

    /** Says so when the server is switched off but the context has suppliers it would serve. */
    @Bean
    @ConditionalOnProperty(prefix = "anycall.server", name = "enabled", havingValue = "false")
    public SmartInitializingSingleton anyCallUnservedSuppliersNotice(ApplicationContext context) {
        return () -> {
            String[] suppliers = context.getBeanNamesForAnnotation(AnyCallSupplier.class);
            if (suppliers.length > 0) {
                log.info("anycall.server.enabled=false: " + suppliers.length
                    + " @AnyCallSupplier bean(s) not served: " + String.join(", ", suppliers));
            }
        };
    }

    static CallOptions callDefaults(AnyCallProperties.Client client) {
        CallOptions options = CallOptions.DEFAULT;
        if (client.getTimeout() != null) {
            options = options.withTimeout(client.getTimeout());
        }
        if (client.getMaxQueueDepth() != null) {
            options = options.withMaxQueueDepth(client.getMaxQueueDepth());
        }
        return options;
    }
}
