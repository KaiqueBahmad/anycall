# AnyCall Example Supplier

Este é um exemplo de **supplier** (servidor) usando a biblioteca AnyCall.

## Descrição

O supplier processa requisições vindas do Redis e executa operações. Neste exemplo, o `ProductSupplier` processa requisições para criar produtos.

## Pré-requisitos

1. Compilar e instalar a biblioteca AnyCall localmente:
```bash
cd ../lib
mvn clean install
```

2. Redis rodando localmente na porta 6379:
```bash
cd ../../..
docker-compose up -d
```

## Executar

```bash
mvn spring-boot:run
```

O supplier ficará escutando requisições na fila Redis do grupo `product-workers`.

## Estrutura

- `ProductSupplier` - Classe anotada com `@AnyCallSupplier` que contém métodos `@Supply`
- `AnyCallConfiguration` - Configura e inicia o servidor AnyCall
- `Product` e `CreateProductRequest` - Models de dados
