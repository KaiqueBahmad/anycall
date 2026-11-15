# Java - AnyCall

This directory contains the Java components of the AnyCall project.
Call functions across Java services using Redis, with no `.proto` files, exposed ports, or extra service plumbing to maintain.

## Structure

- **lib/** - AnyCall core library
- **example-consumer/** - Consumer example
- **example-supplier/** - Supplier example
- **pom.xml** - Maven reactor (parent) configuration; it also builds
  [`anycall-spring`](../../integrations/spring), which lives in `integrations/spring`
- **run-supplier.sh** / **run-consumer.sh** - Scripts to run the examples

## How to use

### Build
```bash
# From this directory (reactor root): builds and installs every module
mvn clean install
```
It only builds; the examples run with the scripts below, or with `-Prun`.

### Run the examples
```bash
./run-supplier.sh
./run-consumer.sh
```

### Quick usage

- **Supplier**: annotate methods with `@Supply`, register the class (or register a function under a name), and start the server.
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
Core library implementing an RPC framework via Redis (Lists as queues). Uses the `AnyCall` factory class to create clients and servers:

- **AnyCall Client**: Interface for invoking remote methods, blocking or not (`client.async()`). Serializes the request to JSON and publishes it to a Redis queue; every response comes back on the client's own queue, where a single reader hands it to the call waiting for it. Takes default `CallOptions` (timeout, queue-depth limit) in `AnyCall.client(...)`, which a call's own `CallOptions` replace; closing it stops everything at once.
  
- **AnyCall Server**: Listener that processes requests from Redis. Each registered method has a read loop of its own, which takes its requests and hands them to a shared worker pool. Methods are discovered via `@Supply` annotation on registered classes, or registered as functions under a name (`register(SupplyMethod, handler)`). Each method's concurrency is optionally capped by `@Supply(maxConcurrency = ...)` (default `1`), with an optional server-wide cap via `AnyCall.server(redisUri, ServerOptions.DEFAULT.withMaxConcurrency(n))`; both can change while it runs. Closing it stops it and releases its Redis connections.

### example-consumer
Client application demonstrating the use of `AnyCallClient`. Fires `CONCURRENCY` calls (1 by default) to the `analyze-sentiment` method at once and logs each response with its latency.

### example-supplier
Server application that registers suppliers via `AnyCall.server()`. The `SentimentAnalyzer` class contains an `analyzeSentiment` method annotated with `@Supply(methodName = "analyze-sentiment")`, which handles sentiment analysis. Starts listeners for each registered method and writes a health file to `$XDG_RUNTIME_DIR/anycall/health` or `/tmp/anycall/health` as fallback.
