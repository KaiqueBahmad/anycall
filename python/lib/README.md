# AnyCall Library

Biblioteca Redis-based para RPC em Python. Fornece um framework para comunicação entre aplicações através de Redis Streams.

## Visão Geral

AnyCall é um framework que permite que aplicações Python se comuniquem de forma assíncrona através do Redis, utilizando Redis Streams como mecanismo de transporte de mensagens.

## Componentes Principais

### Core
- **AnyCall** - Interface principal da biblioteca
- **AnyCallClient** - Cliente para chamar métodos em suppliers remotos
- **AnyCallServer** - Servidor para registrar e executar métodos
- **RedisStreamAdapter** - Adaptador para Redis Streams

### Configuração
- **AnycallProperties** - Propriedades de configuração da biblioteca
- **supply** - Decorador para marcar métodos como supply

### Modelos
- **AnyCallRequest** - Modelo de requisição RPC
- **AnyCallResponse** - Modelo de resposta RPC

## Build

```bash
uv sync
```

Isso irá instalar a biblioteca e suas dependências.

## Uso Básico

1. Implemente um supplier usando o decorador `@supply`
2. Configure e inicie o `AnyCallServer`
3. Use `AnyCallClient` para chamar métodos remotamente

Ver `example-supplier` e `example-consumer` para exemplos práticos.

## Dependências

- Redis
- Python 3.9+

## Configuração

Configure as propriedades através de `AnycallProperties`:

```python
from datetime import timedelta
from anycall import AnyCall

props = AnycallProperties(
    timeout=timedelta(seconds=30),
    metrics_enabled=True
)
```

Ou use os valores padrão:

```python
from anycall import AnyCall

client = AnyCall.client("redis://localhost:6379")
```
