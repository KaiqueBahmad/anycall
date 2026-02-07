package kaiquebt.dev.anycall;

import org.springframework.boot.autoconfigure.AutoConfiguration;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.context.annotation.ComponentScan;

@AutoConfiguration
@EnableConfigurationProperties(AnycallProperties.class)
@ComponentScan(basePackages = "kaiquebt.dev.anycall")
public class AnycallAutoConfiguration {

}
