# Projeto Java - AnyCall

Este diretório contém os componentes Java do projeto AnyCall.

## Estrutura

- **lib/** - Biblioteca principal do AnyCall
- **example-consumer/** - Exemplo de consumer
- **example-supplier/** - Exemplo de supplier
- **Dockerfile** - Imagem Docker para o projeto
- **pom.xml** - Configuração do Maven
- **rebuild-all.sh** - Script para reconstruir todos os módulos

## Como usar

### Compilar
```bash
./rebuild-all.sh
```

Para detalhes sobre como usar como supplier ou consumer, veja [USAGE.md](USAGE.md).

## Módulos

### lib
Biblioteca principal implementando um framework de RPC via Redis Streams. Utiliza a classe factory `AnyCall` para criar clients e servers:

- **AnyCall Client**: Interface síncrona para invocar métodos remotos. Serializa a requisição em JSON, publica em uma Redis Stream, aguarda a resposta em um stream de callback. Suporta timeout configurável e coleta opcional de métricas.
  
- **AnyCall Server**: Listener que processa requisições do Redis. Mantém um pool de threads (um por método registrado) consumindo de streams específicas. Os métodos são descobertos via anotação `@Supply` nas classes registradas.

- **Publisher**: Abstração para publicação em Redis Streams (mensagens JSON ou raw).

- **Configuração**: Via `AnycallProperties` — define parâmetros como Redis URI, timeouts, thread pools, etc.

### example-consumer
Aplicação cliente que demonstra o uso do `AnyCallClient`. Faz 100 chamadas RPC para o método `create-new-product` e exibe estatísticas de latência (min, avg, p50, p95, p99, max). Inclui aquecimento inicial e suporte a métricas.

### example-supplier
Aplicação servidor que registra suppliers via `AnyCall.server()`. A classe `ProductSupplier` contém um método `createNewProduct` anotado com `@Supply("create-new-product")`, que processa criação de produtos. Inicia listeners para cada método registrado e escreve um arquivo de saúde em `/tmp/anycall/health`.
