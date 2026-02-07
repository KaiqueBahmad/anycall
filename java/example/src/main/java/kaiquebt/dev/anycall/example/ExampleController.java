package kaiquebt.dev.anycall.example;

import kaiquebt.dev.anycall.AnycallProperties;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * Example controller demonstrating how to use AnyCall configuration properties.
 */
@RestController
public class ExampleController {

    private final AnycallProperties anycallProperties;

    public ExampleController(AnycallProperties anycallProperties) {
        this.anycallProperties = anycallProperties;
    }

    @GetMapping("/config")
    public String getConfig() {
        return "AnyCall foo property: " + anycallProperties.foo();
    }
}
