# AnyCall Java Usage Guide

## How to Use as Supplier (Server)

1. **Define a class with methods annotated with `@Supply`:**
```java
public class ProductSupplier {
    @Supply("create-new-product")
    public Product createNewProduct(CreateProductRequest req) {
        return new Product(req.getName(), req.getPriceInCents());
    }
}
```

2. **Register and start the server:**
```java
String redisUri = System.getenv("REDIS_URI");
AnyCallServer server = AnyCall.server(redisUri);
server.register(new ProductSupplier());
server.start();
```

## How to Use as Consumer (Client)

### Call with explicit type:
```java
AnyCallClient client = AnyCall.client("redis://localhost:6379");
Product product = client.call("create-new-product", request, Product.class);
```

### Call with registry (register types once):
```java
AnyCallClient client = AnyCall.client("redis://localhost:6379");
client.registerType("create-new-product", Product.class);

// Then, calls without type:
Product product = client.call("create-new-product", request);
```

### Call without model (returns Map):
```java
Map<String, Object> response = client.callRaw("create-new-product", request);
```

## Configuration

```java
// Custom timeout
AnyCallClient client = AnyCall.client(redisUri, Duration.ofSeconds(60));

// With metrics
AnyCallClient client = AnyCall.client(redisUri, true);

// Both
AnyCallClient client = AnyCall.client(redisUri, Duration.ofSeconds(60), true);
```
