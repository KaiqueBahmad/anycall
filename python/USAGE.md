# Guia de Uso - AnyCall Python

## Como Usar como Supplier (Servidor)

1. **Defina uma classe com métodos decorados com `@supply`:**
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

2. **Registre e inicie o servidor:**
```python
from anycall import AnyCall

server = AnyCall.server("redis://localhost:6379")
server.register(ProductSupplier())
server.start()
```

## Como Usar como Consumer (Cliente)

### Chamada com tipo explícito:
```python
client = AnyCall.client("redis://localhost:6379")
product = client.call("create-new-product", request, Product)
```

### Chamada com registry (registre tipos uma vez):
```python
client = AnyCall.client("redis://localhost:6379")
client.register_type("create-new-product", Product)

# Depois, chamadas sem tipo:
product = client.call("create-new-product", request)
```

### Chamada sem modelo (retorna dict):
```python
response = client.call_raw("create-new-product", request)
```

## Configuração

```python
from datetime import timedelta

# Timeout customizado
client = AnyCall.client(redis_uri, timeout=timedelta(seconds=60))

# Com métricas
client = AnyCall.client(redis_uri, metrics_enabled=True)

# Ambos
client = AnyCall.client(
    redis_uri,
    timeout=timedelta(seconds=60),
    metrics_enabled=True
)
```
