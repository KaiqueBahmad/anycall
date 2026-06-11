# Python - AnyCall

This directory contains the Python components of the AnyCall project.
Call functions across Python services using Redis, with no `.proto` files, exposed ports, or extra service plumbing to maintain.

## Structure

- **lib/** - AnyCall core library
- **example-consumer/** - Consumer example
- **example-supplier/** - Supplier example
- **Dockerfile** - Docker image for the project
- **pyproject.toml** - uv workspace configuration
- **rebuild-all.sh** - Script to rebuild all modules

## How to use

### Build
```bash
./rebuild-all.sh
```

### Quick usage

- **Supplier**: decorate methods with `@supply`, register the class, and start the server.
- **Consumer**: create an `AnyCall` client and call the supplier method by name.

```python
server = AnyCall.server(redis_uri)
server.register(SentimentAnalyzer())
server.start()

client = AnyCall.client(redis_uri)
sentiment = client.call("analyze-sentiment", request, Sentiment)
```

For details on how to use as a supplier or consumer, see USAGE.md.

## Modules

### lib
Core library implementing an RPC framework via Redis Streams. Uses the `AnyCall` factory class to create clients and servers:

- **AnyCall Client**: Synchronous interface for invoking remote methods. Serializes the request to JSON, publishes to a Redis Stream, waits for the response on a callback stream. Supports configurable timeout and optional metrics collection.
  
- **AnyCall Server**: Listener that processes requests from Redis. Maintains a thread pool (one per registered method) consuming from specific streams. Methods are discovered via the `@supply` decorator on registered classes.

- **Configuration**: Via `AnycallProperties` — defines parameters like Redis URI, timeouts, thread pools, etc.

### example-consumer
Client application demonstrating the use of `AnyCallClient`. Makes 100 RPC calls to the `analyze-sentiment` method and displays latency statistics (min, avg, p50, p95, p99, max). Includes warmup call and metrics support.

### example-supplier
Server application that registers suppliers via `AnyCall.server()`. The `SentimentAnalyzer` class contains an `analyze_sentiment` method decorated with `@supply("analyze-sentiment")`, which handles sentiment analysis. Starts listeners for each registered method and writes a health file to `/tmp/anycall/health`.
