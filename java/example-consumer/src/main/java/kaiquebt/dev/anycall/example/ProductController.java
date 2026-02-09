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

    @PostMapping("/products")
    public Product createProduct(@RequestBody CreateProductRequest request) {
        long startTime = System.currentTimeMillis();
        Product product = anyCall.call("create-new-product", request, Product.class);
        long endTime = System.currentTimeMillis();
        System.out.println("Execution time: " + (endTime - startTime) + "ms");
        
        
        System.out.println(product);
        return product;
    }
}
