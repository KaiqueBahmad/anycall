package dev.kaiquebt.anycall.example;

import dev.kaiquebt.anycall.annotation.Supply;
import dev.kaiquebt.anycall.example.model.CreateProductRequest;
import dev.kaiquebt.anycall.example.model.Product;

public class ProductSupplier {

    @Supply("create-new-product")
    public Product createNewProduct(CreateProductRequest req) {
        return new Product(req.name(), req.priceInCents());
    }
}
