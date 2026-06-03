package kaiquebt.dev.anycall.example;

import kaiquebt.dev.anycall.annotation.Supply;
import kaiquebt.dev.anycall.example.model.CreateProductRequest;
import kaiquebt.dev.anycall.example.model.Product;

public class ProductSupplier {

    @Supply("create-new-product")
    public Product createNewProduct(CreateProductRequest req) {
        return new Product(req.name(), req.priceInCents());
    }
}
