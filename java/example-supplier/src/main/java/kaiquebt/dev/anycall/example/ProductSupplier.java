package kaiquebt.dev.anycall.example;

import kaiquebt.dev.anycall.AnyCallSupplier;
import kaiquebt.dev.anycall.Supply;
import kaiquebt.dev.anycall.example.model.CreateProductRequest;
import kaiquebt.dev.anycall.example.model.Product;

/**
 * Example supplier that handles product creation requests.
 */
@AnyCallSupplier
public class ProductSupplier {

    @Supply("create-new-product")
    public Product createNewProduct(CreateProductRequest req) {
        return new Product(req.name(), req.priceInCents());
    }
}
