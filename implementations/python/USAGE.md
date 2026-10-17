# AnyCall Python Usage Guide

## How to Use as Supplier (Server)

1. **Define a class with methods decorated with `@supply`:**
```python
from anycall import AnycallContext, supply
from dataclasses import dataclass

@dataclass
class TextRequest:
    text: str

@dataclass
class Sentiment:
    text: str
    label: str

class SentimentAnalyzer:
    @supply("analyze-sentiment")
    def analyze_sentiment(self, ctx: AnycallContext, req: TextRequest) -> Sentiment:
        return Sentiment(text=req.text, label="positive")
```

`@supply` accepts an optional `max_concurrency` (default `1`): how many requests for
that operation a single server instance may process at the same time.
```python
    @supply("analyze-sentiment", max_concurrency=4)
    def analyze_sentiment(self, ctx: AnycallContext, req: TextRequest) -> Sentiment:
        ...
```

2. **Register and start the server:**
```python
from anycall import AnyCall

server = AnyCall.server("redis://localhost:16379")
server.register(SentimentAnalyzer())
server.start()
```

Pass `max_concurrency` to `AnyCall.server(...)` for a server-wide cap across every
registered method combined:
```python
server = AnyCall.server("redis://localhost:16379", max_concurrency=16)
```

### If a server dies mid-request

If a server crashes while processing a request, another live server notices
within ~8–10s and fails the request back: the client gets a `ServerLostError`
instead of waiting out its `timeout`. With a single server, the client still
waits for its timeout. The request is not retried, and may have partially run.

A `TimeoutError` says nothing about the server: it may be slow, may never have
taken the request, or may have been lost too recently to be noticed.

## How to Use as Consumer (Client)

### Call with explicit type:
```python
client = AnyCall.client("redis://localhost:16379")
sentiment = client.call("analyze-sentiment", request, Sentiment)
```

### Call with registry (register types once):
```python
client = AnyCall.client("redis://localhost:16379")
client.register_type("analyze-sentiment", Sentiment)

# Then, calls without type:
sentiment = client.call("analyze-sentiment", request)
```

### Call without model (returns dict):
```python
response = client.raw_call("analyze-sentiment", request)
```

### Fail fast if no server is available:
```python
from anycall.exceptions import NoServerAvailableError

try:
    sentiment = client.call("analyze-sentiment", request, Sentiment)
except NoServerAvailableError:
    ...  # no server has heartbeated recently; not submitted
```
Every call checks the heartbeat registry before publishing the request, the
same way a plain HTTP call would get connection-refused instead of hanging:
without this, a request sitting in an empty queue would just wait out the
full `timeout` with nothing to pop it. This only confirms *some* server is
alive, not that one of them supports the method being called.

### Reject when the backlog is too deep:
```python
from anycall.exceptions import QueueFullError

try:
    sentiment = client.call("analyze-sentiment", request, Sentiment, max_queue_depth=100)
except QueueFullError:
    ...  # the request stream already had >= 100 pending entries; not submitted
```

A client-wide default can be set instead of passing `max_queue_depth` on every call:
```python
client = AnyCall.client(redis_uri, default_max_queue_depth=100)
client.set_default_max_queue_depth(200)  # change it later
client.get_default_max_queue_depth()     # -> 200
```

### Check the current backlog:
```python
depth = client.get_queue_depth("analyze-sentiment")  # XLEN of the request stream
```

## Configuration

```python
from datetime import timedelta

# Custom timeout
client = AnyCall.client(redis_uri, timeout=timedelta(seconds=60))

# With metrics
client = AnyCall.client(redis_uri, metrics_enabled=True)

# Both
client = AnyCall.client(
    redis_uri,
    timeout=timedelta(seconds=60),
    metrics_enabled=True
)
```

By default a call waits for its response with no limit (`timedelta(0)`).
