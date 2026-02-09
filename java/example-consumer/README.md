# AnyCall Example Consumer

Este é um exemplo de **consumer** (cliente) usando a biblioteca AnyCall.

## Descrição

O consumer envia requisições para o Redis que serão processadas por qualquer supplier disponível. Neste exemplo, o `ProductController` expõe uma API REST que internamente faz chamadas remotas via AnyCall.

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

3. Pelo menos um supplier rodando (veja `example-supplier`)

## Executar

```bash
mvn spring-boot:run
```

A aplicação irá iniciar na porta 8080.

## Testar

```bash
curl -X POST http://localhost:8080/products \
  -H "Content-Type: application/json" \
  -d '{"name":"Keyboard","priceInCents":10000}'
```

## Estrutura

- `ProductController` - REST controller que usa `AnyCallClient` para fazer chamadas remotas
- `Product` e `CreateProductRequest` - Models de dados
