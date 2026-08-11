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
