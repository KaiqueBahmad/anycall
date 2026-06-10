# AnyCall Library

Biblioteca Redis-based para RPC em Java. Fornece um framework para comunicação entre aplicações através de Redis Streams.

## Visão Geral

AnyCall é um framework que permite que aplicações Java se comuniquem de forma assíncrona através do Redis, utilizando Redis Streams como mecanismo de transporte de mensagens.

## Componentes Principais

### Core
- **AnyCall** - Interface principal da biblioteca
- **AnyCallClient** - Cliente para chamar métodos em suppliers remotos
- **AnyCallServer** - Servidor para registrar e executar métodos
- **AnyCallSupplier** - Interface para implementar suppliers (provedores de serviços)
- **RedisStreamAdapter** - Adaptador para Redis Streams

### Publisher
- **AnyCallPublisher** - Publica mensagens/requisições
- **AnycallQueues** - Gerencia filas de mensagens

### Configuração
- **AnycallProperties** - Propriedades de configuração da biblioteca
- **Supply** - Anotação para marcar métodos como supply

### Modelos
- **AnyCallRequest** - Modelo de requisição RPC
- **AnyCallResponse** - Modelo de resposta RPC

## Build

```bash
./mvnw clean install
```

Isso irá compilar e instalar a biblioteca no repositório Maven local.

## Uso Básico

1. Implemente um supplier usando a anotação `@Supply`
2. Configure e inicie o `AnyCallServer`
3. Use `AnyCallClient` para chamar métodos remotamente

Ver `example-supplier` e `example-consumer` para exemplos práticos.

## Dependências

- Redis
- Java 11+

## Configuração

Configure as propriedades através de `AnycallProperties`:

```java
AnycallProperties props = new AnycallProperties(
    Duration.ofSeconds(30),  // timeout
    true                      // metricsEnabled
);
```

Ou use os valores padrão:

```java
AnycallProperties props = new AnycallProperties();
```
