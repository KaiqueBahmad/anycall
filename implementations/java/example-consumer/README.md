# AnyCall Example Consumer

This is an example of a **consumer** (client) using the AnyCall library.

## Description

The consumer sends requests to Redis that will be processed by any available supplier. In this example, the `ConsumerApplication` makes 100 RPC calls to the `analyze-sentiment` operation and displays latency statistics.

## Prerequisites

1. Build and install the AnyCall library locally:
```bash
cd ../lib
mvn clean install
```

2. Redis running locally on port 16379:
```bash
cd ../../..
docker-compose up -d
```

3. At least one supplier running (see `example-supplier`)

## Running

```bash
mvn spring-boot:run
```

The application will make 100 calls to the sentiment analyzer and print latency statistics.

## Structure

- `ConsumerApplication` - Entry point that uses `AnyCallClient` to make remote calls
- `Sentiment` and `TextRequest` - Data models
