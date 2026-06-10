# anycall

Esta biblioteca pretende fornecer um mecanismo simples de chamadas remotas
entre serviços, utilizando o Redis como uma pool distribuída de mensagens.
O cliente publica uma requisição no Redis, que pode ser consumida por
qualquer servidor disponível. A chamada pode ser tratada de forma
síncrona (bloqueando até a resposta) ou assíncrona, caso a linguagem
ou o runtime permitam, retornando futures, promises ou callbacks.
Esse modelo oferece balanceamento de carga automático, escalabilidade
horizontal e baixo acoplamento entre serviços, mantendo uma API simples
e consistente entre diferentes linguagens.

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
String redisUri = "redis://localhost:6379";
AnyCallClient anyCall = AnyCall.client(redisUri);

CreateProductRequest req = new CreateProductRequest("Keyboard", 10000);
Product product = anyCall.call("create-new-product", req, Product.class);
System.out.println(product);
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

---

### Node.js (TypeScript)

**Server**
```typescript
import { supply, startServer } from "anycall";

supply("create-new-product", async (payload) => {
    return {
        name: payload.name,
        price: payload.price
    };
});

startServer({
    redisUrl: "redis://localhost:6379",
    group: "product-workers"
});
```

**Client**
```typescript
import { AnyCallClient } from "anycall";

const client = new AnyCallClient({
    redisUrl: "redis://localhost:6379"
});

const product = await client.call(
    "create-new-product",
    { name: "Monitor", price: 20000 }
);
console.log(product);
```

---

### Go

**Server**
```go
import "anycall"

anycall.Supply("create-new-product", func(payload anycall.Payload) any {
    return map[string]any{
        "name":  payload["name"],
        "price": payload["price"],
    }
})

anycall.StartServer(anycall.Config{
    RedisURL: "redis://localhost:6379",
    Group:    "product-workers",
})
```

**Client**
```go
import (
    "anycall"
    "fmt"
    "time"
)

client := anycall.NewClient("redis://localhost:6379")
result, err := client.Call(
    "create-new-product",
    map[string]any{
        "name":  "Laptop",
        "price": 300000,
    },
    3*time.Second,
)
fmt.Println(result)
```
