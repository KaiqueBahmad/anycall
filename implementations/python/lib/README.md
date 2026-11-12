# Python - AnyCall (core library)

This directory contains the AnyCall core library for Python (published as
`anycall-py`). Call functions across Python services using Redis, with no
`.proto` files, exposed ports, or extra service plumbing to maintain.

[`../example-consumer/`](../example-consumer) and
[`../example-supplier/`](../example-supplier).

## Structure

- **src/anycall/** - AnyCall core library package
- **pyproject.toml** - Package metadata and dependencies
- **TESTING.md** - How to run the test suite

## How to use

### Install

```bash
# Using uv (recommended)
uv sync

# Or using pip
pip install -e .
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

For details on how to use as a supplier or consumer, see [USAGE.md](../USAGE.md).

## Modules

### lib
Core library implementing an RPC framework via Redis (Lists as queues). Uses the `AnyCall` factory class to create clients and servers:

- **AnyCall Client**: Synchronous interface for invoking remote methods. Serializes the request to JSON, publishes to a Redis queue, waits for the response on a callback queue. Supports a configurable timeout and a default queue-depth limit, both passed to `AnyCall.client(...)`.
  
- **AnyCall Server**: Listener that processes requests from Redis. Each registered method gets its own read loop, and taken requests run on a shared worker pool. Methods are discovered via the `@supply` decorator on registered classes. Each method's concurrency is optionally capped by `@supply(max_concurrency=...)` (default `1`), with an optional server-wide cap via `AnyCall.server(redis_uri, max_concurrency=...)`.

### example-consumer
Client application demonstrating the use of `AnyCallClient`. Makes one call to the `analyze-sentiment` method and logs the response.

### example-supplier
Server application that registers suppliers via `AnyCall.server()`. The `SentimentAnalyzer` class contains an `analyze_sentiment` method decorated with `@supply("analyze-sentiment")`, which handles sentiment analysis. Starts listeners for each registered method.
