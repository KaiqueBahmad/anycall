# AnyCall Python Usage Guide

## How to Use as Supplier (Server)

1. **Define a class with methods decorated with `@supply`:**
```python
from anycall import supply
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
```

2. **Register and start the server:**
```python
from anycall import AnyCall

server = AnyCall.server("redis://localhost:6379")
server.register(ProductSupplier())
server.start()
```

## How to Use as Consumer (Client)

### Call with explicit type:
```python
client = AnyCall.client("redis://localhost:6379")
product = client.call("create-new-product", request, Product)
```

### Call with registry (register types once):
```python
client = AnyCall.client("redis://localhost:6379")
client.register_type("create-new-product", Product)

# Then, calls without type:
product = client.call("create-new-product", request)
```

### Call without model (returns dict):
```python
response = client.call_raw("create-new-product", request)
```

## Configuration

```python
from datetime import timedelta

# Custom timeout
client = AnyCall.client(redis_uri, timeout=timedelta(seconds=60))

# With metrics
client = AnyCall.client(redis_uri, metrics_enabled=True)

# Both
client = AnyCall.client(
    redis_uri,
    timeout=timedelta(seconds=60),
    metrics_enabled=True
)
```
