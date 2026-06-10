# Guia de Uso - AnyCall Java

## Como Usar como Supplier (Servidor)

1. **Defina uma classe com métodos anotados com `@Supply`:**
```java
public class MyService {
    @Supply("my-operation")
    public MyResponse handleRequest(MyRequest req) {
        // Sua lógica aqui
        return new MyResponse(req.getValue());
    }
}
```

2. **Registre e inicie o servidor:**
```java
String redisUri = System.getenv("REDIS_URI");
AnyCallServer server = AnyCall.server(redisUri);
server.register(new MyService());
server.start();
```

O servidor escuta automaticamente streams Redis com o nome do método (`my-operation`), processa requisições e envia respostas. Use `server.register(supplier1, supplier2)` para registrar múltiplos suppliers.

## Como Usar como Consumer (Cliente)

1. **Crie um cliente:**
```java
String redisUri = System.getenv("REDIS_URI");
AnyCallClient client = AnyCall.client(redisUri);
```

2. **Faça chamadas remotas:**
```java
MyRequest request = new MyRequest("test");
MyResponse response = client.call("my-operation", request, MyResponse.class);
```

O client serializa a requisição em JSON, publica em Redis e aguarda a resposta (timeout padrão 30s). Para timeout customizado: `AnyCall.client(redisUri, Duration.ofSeconds(60))`. Para habilitar métricas: `AnyCall.client(redisUri, true)`.
