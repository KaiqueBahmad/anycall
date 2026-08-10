# Java - AnyCall

This directory contains the Java components of the AnyCall project.
Call functions across Java services using Redis, with no `.proto` files, exposed ports, or extra service plumbing to maintain.

## Structure

- **lib/** - AnyCall core library
- **example-consumer/** - Consumer example
- **example-supplier/** - Supplier example
- **pom.xml** - Maven reactor (parent) configuration
- **run-supplier.sh** / **run-consumer.sh** - Scripts to run the examples

## How to use

### Build
```bash
# From this directory (reactor root)
mvn clean install
```

### Run the examples
```bash
./run-supplier.sh
./run-consumer.sh
```

### Quick usage

- **Supplier**: annotate methods with `@Supply`, register the class, and start the server.
- **Consumer**: create an `AnyCallClient` and call the supplier method by name.

```java
AnyCallServer server = AnyCall.server(redisUri);
server.register(new SentimentAnalyzer());
server.start();

AnyCallClient client = AnyCall.client(redisUri);
Sentiment sentiment = client.call("analyze-sentiment", request, Sentiment.class);
```

For details on how to use as a supplier or consumer, see [USAGE.md](USAGE.md).

## Modules

### lib
Core library implementing an RPC framework via Redis Streams. Uses the `AnyCall` factory class to create clients and servers:

- **AnyCall Client**: Synchronous interface for invoking remote methods. Serializes the request to JSON, publishes to a Redis Stream, waits for the response on a callback stream. Supports configurable timeout and optional metrics collection.
  
- **AnyCall Server**: Listener that processes requests from Redis. Maintains a thread pool (one per registered method) consuming from specific streams. Methods are discovered via `@Supply` annotation on registered classes.

- **Publisher**: Abstraction for publishing to Redis Streams (JSON messages).

- **Configuration**: Via `AnycallProperties` — defines parameters like Redis URI, timeouts, thread pools, etc.

### example-consumer
Client application demonstrating the use of `AnyCallClient`. Makes 100 RPC calls to the `analyze-sentiment` method and displays latency statistics (min, avg, p50, p95, p99, max). Includes warmup call and metrics support.

### example-supplier
Server application that registers suppliers via `AnyCall.server()`. The `SentimentAnalyzer` class contains an `analyzeSentiment` method annotated with `@Supply(methodName = "analyze-sentiment")`, which handles sentiment analysis. Starts listeners for each registered method and writes a health file to `$XDG_RUNTIME_DIR/anycall/health` or `/tmp/anycall/health` as fallback.
