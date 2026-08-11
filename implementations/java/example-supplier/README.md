# AnyCall Example Supplier

This is an example of a **supplier** (server) using the AnyCall library.

## Description

The supplier processes requests from Redis and executes operations. In this example, the `SentimentAnalyzer` processes requests to analyze sentiment from text.

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

## Running

```bash
mvn spring-boot:run
```

The supplier will listen for requests on the Redis stream for the `analyze-sentiment` operation.

## Structure

- `SentimentAnalyzer` - Class with method decorated with `@Supply` 
- `AnyCallConfiguration` - Configures and starts the AnyCall server
- `Sentiment` and `TextRequest` - Data models
