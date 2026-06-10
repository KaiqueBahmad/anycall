# anycall

Call functions across services written in different languages, using the
Redis you already have — no .proto files, no exposed ports, no per-service
plumbing to maintain.

A client publishes a request to Redis; any available server can pick it up,
run it, and return the result. Calls can be synchronous (block until the
response) or asynchronous (futures, promises, or callbacks), depending on
the language and runtime.

Because the broker sits in the middle — unlike point-to-point RPC such as
gRPC — you get automatic load balancing, horizontal scaling, and loose
coupling between services for free, with one consistent API across languages.

**Status:** Java and Python are under active development. The examples below
reflect the current target API.

## Exemplos de Uso

### Java

**Server**
```java
public class ProductSupplier {
    @Supply("create-new-product")
    public Product createNewProduct(CreateProductRequest req) {
        return new Product(req.name(), req.priceInCents());
    }
}

public class Application {
    public static void main(String[] args) {
        String redisUri = "redis://localhost:6379";
        AnyCallServer server = AnyCall.server(redisUri);
        server.register(new ProductSupplier());
        server.start();
    }
}
```

**Client**
```java
public class Application {
    public static void main(String[] args) {
        String redisUri = "redis://localhost:6379";
        AnyCallClient anyCall = AnyCall.client(redisUri);

        CreateProductRequest req = new CreateProductRequest("Keyboard", 10000);
        Product product = anyCall.call("create-new-product", req, Product.class);
        System.out.println(product);
    }
}
```

[→ Ver mais](java/README.md)

---

### Python

**Server**
```python
from anycall import AnyCall, supply
from dataclasses import dataclass

@dataclass
class CreateProductRequest:
    name: str
    price_in_cents: int

@dataclass
class Product:
    name: str
    price_in_cents: int

class ProductSupplier:
    @supply("create-new-product")
    def create_new_product(self, req: CreateProductRequest) -> Product:
        return Product(name=req.name, price_in_cents=req.price_in_cents)

if __name__ == "__main__":
    server = AnyCall.server("redis://localhost:6379")
    server.register(ProductSupplier())
    server.start()
```

**Client**
```python
from anycall import AnyCall
from dataclasses import dataclass

@dataclass
class CreateProductRequest:
    name: str
    price_in_cents: int

client = AnyCall.client("redis://localhost:6379")
product = client.call(
    "create-new-product",
    CreateProductRequest(name="Mouse", price_in_cents=5000)
)
print(product)  # Returns dict: {"name": "Mouse", "price_in_cents": 5000}
```

[→ Ver mais](python/README.md)
