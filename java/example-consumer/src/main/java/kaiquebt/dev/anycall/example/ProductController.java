package kaiquebt.dev.anycall.example;

import kaiquebt.dev.anycall.AnyCallClient;
import kaiquebt.dev.anycall.example.model.CreateProductRequest;
import kaiquebt.dev.anycall.example.model.Product;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RestController;

/**
 * Example controller demonstrating how to use AnyCall client.
 */
@RestController
public class ProductController {

    private final AnyCallClient anyCall;

    public ProductController(AnyCallClient anyCall) {
        this.anyCall = anyCall;
    }

    @PostMapping("/ping")
    public String createProduct() {
        long startTime = System.currentTimeMillis();
        anyCall.call("create-new-product", new CreateProductRequest("teste", 123), Product.class);
        long endTime = System.currentTimeMillis();
        return (endTime - startTime)+ "";
    }
}
