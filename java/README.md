# AnyCall Java Implementation

Este diretório contém a implementação Java da biblioteca AnyCall e exemplos de uso.

## 📦 Estrutura

```
java/
├── lib/                    # Biblioteca AnyCall
├── example-supplier/       # Exemplo de servidor (supplier)
├── example-consumer/       # Exemplo de cliente (consumer)
└── make-request.sh        # Script para testar a aplicação
```

## 🚀 Quick Start

### 1. Compilar e instalar a biblioteca

```bash
cd lib
mvn clean install
```

### 2. Iniciar o Redis

Na raiz do projeto:

```bash
cd ../..
docker-compose up -d
```

### 3. Iniciar o Supplier (Terminal 1)

```bash
cd example-supplier
mvn spring-boot:run
```

O supplier ficará escutando requisições na fila Redis.

### 4. Iniciar o Consumer (Terminal 2)

```bash
cd example-consumer
mvn spring-boot:run
```

O consumer iniciará na porta 8080.

### 5. Fazer uma requisição de teste

No diretório `java/`, execute:

```bash
./make-request.sh
```

Ou manualmente com curl:

```bash
curl -X POST http://localhost:8080/products \
  -H "Content-Type: application/json" \
  -d '{"name":"Keyboard","priceInCents":10000}'
```

## ⚙️ Configuração

### Habilitar métricas

Edite o `application.properties` de cada exemplo:

```properties
# Habilita logs detalhados com timestamps de cada etapa
anycall.metrics-enabled=true
```

### Configurar timeout

```properties
# Timeout padrão: 30 segundos
anycall.timeout=30s
```

### Configurar Redis

```properties
spring.data.redis.host=localhost
spring.data.redis.port=6379
```

## 📊 Métricas

Com `anycall.metrics-enabled=true`, você verá logs detalhados:

**Cliente (Consumer):**
- Tempo de serialização da requisição
- Tempo de envio para Redis
- Tempo de espera pela resposta
- Tempo de desserialização
- Tempo total

**Servidor (Supplier):**
- Tempo de desserialização da requisição
- Tempo de execução do método
- Tempo de serialização da resposta
- Tempo de envio
- Tempo total de processamento

## 🔧 Desenvolvimento

### Estrutura da API Pública

A API pública (pacote raiz) contém apenas:

- `AnyCall` - Factory para criar servidores
- `AnyCallClient` - Interface para fazer chamadas remotas
- `AnyCallServer` - Interface do servidor
- `@AnyCallSupplier` - Anotação para classes fornecedoras
- `@Supply` - Anotação para métodos remotos
- `AnyCallException` - Exceção da biblioteca

Detalhes de implementação ficam no pacote `impl`.

### Criar um novo Supplier

```java
@AnyCallSupplier
public class MySupplier {
    @Supply("my-method")
    public MyResponse myMethod(MyRequest req) {
        // Sua lógica aqui
        return new MyResponse(...);
    }
}
```

### Configurar o Servidor

```java
@Bean
AnyCallServer anyCallServer(ApplicationContext context) {
    return AnyCall.server(context)
                  .group("my-workers")
                  .start();
}
```

### Usar o Cliente

```java
@Autowired
private AnyCallClient anyCall;

public void makeCall() {
    MyRequest req = new MyRequest(...);
    MyResponse res = anyCall.call("my-method", req, MyResponse.class);
}
```

## 🐛 Troubleshooting

**Erro: Connection refused**
- Verifique se o Redis está rodando: `docker ps`
- Inicie o Redis: `docker-compose up -d`

**Erro: Timeout waiting for response**
- Verifique se o supplier está rodando
- Verifique se o supplier registrou o método correto
- Aumente o timeout se necessário

**Erro: No methods annotated with @Supply found**
- Certifique-se de que suas classes estão anotadas com `@AnyCallSupplier`
- Verifique o package scanning no Spring Boot
