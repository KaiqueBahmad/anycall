# Guia de Uso - AnyCall Java

## Como Usar como Supplier (Servidor)

1. **Defina uma classe com métodos anotados com `@Supply`:**
```java
public class ProductSupplier {
    @Supply("create-new-product")
    public Product createNewProduct(CreateProductRequest req) {
        return new Product(req.getName(), req.getPriceInCents());
    }
}
```

2. **Registre e inicie o servidor:**
```java
String redisUri = System.getenv("REDIS_URI");
AnyCallServer server = AnyCall.server(redisUri);
server.register(new ProductSupplier());
server.start();
```

## Como Usar como Consumer (Cliente)

### Chamada com tipo explícito:
```java
AnyCallClient client = AnyCall.client("redis://localhost:6379");
Product product = client.call("create-new-product", request, Product.class);
```

### Chamada com registry (registre tipos uma vez):
```java
AnyCallClient client = AnyCall.client("redis://localhost:6379");
client.registerType("create-new-product", Product.class);

// Depois, chamadas sem tipo:
Product product = client.call("create-new-product", request);
```

### Chamada sem modelo (retorna Map):
```java
Map<String, Object> response = client.callRaw("create-new-product", request);
```

## Configuração

```java
// Timeout customizado
AnyCallClient client = AnyCall.client(redisUri, Duration.ofSeconds(60));

// Com métricas
AnyCallClient client = AnyCall.client(redisUri, true);

// Ambos
AnyCallClient client = AnyCall.client(redisUri, Duration.ofSeconds(60), true);
```
