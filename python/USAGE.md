# Guia de Uso - AnyCall Python

## Como Usar como Supplier (Servidor)

1. **Defina uma classe com métodos decorados com `@supply`:**
```python
from anycall import supply

class MyService:
    @supply("my-operation")
    def handle_request(self, req: MyRequest) -> MyResponse:
        # Sua lógica aqui
        return MyResponse(req.value)
```

2. **Registre e inicie o servidor:**
```python
from anycall import AnyCall

redis_uri = "redis://localhost:6379"
server = AnyCall.server(redis_uri)
server.register(MyService())
server.start()
```

O servidor escuta automaticamente streams Redis com o nome do método (`my-operation`), processa requisições e envia respostas. Use `server.register(supplier1, supplier2)` para registrar múltiplos suppliers.

## Como Usar como Consumer (Cliente)

1. **Crie um cliente:**
```python
from anycall import AnyCall

redis_uri = "redis://localhost:6379"
client = AnyCall.client(redis_uri)
```

2. **Faça chamadas remotas:**
```python
request = MyRequest("test")
response = client.call("my-operation", request)  # Returns dict by default
```

Você pode opcionalmente especificar um tipo de resposta para desserialização:
```python
response = client.call("my-operation", request, MyResponse)
```

O client serializa a requisição em JSON, publica em Redis e aguarda a resposta (timeout padrão 30s). Para timeout customizado: `AnyCall.client(redis_uri, timeout=timedelta(seconds=60))`. Para habilitar métricas: `AnyCall.client(redis_uri, metrics_enabled=True)`.
