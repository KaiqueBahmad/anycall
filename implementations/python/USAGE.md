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
instead of waiting out its `timeout`. If no other server is alive, the waiting
client notices on its own at the end of its current 10s wait, so the error
comes 8–18s after the crash. The request is not retried, and may have
partially run.

A `TimeoutError` says nothing about the server: it may be slow, may never have
taken the request, or may have been lost too recently to be noticed.

How it works: [docs/reaping.md](../../docs/reaping.md).

### If Redis fails mid-call

If a Redis command fails during a call (the connection drops, Redis restarts
or stops answering for 15s), the call raises a `BrokerError`, with redis-py's
exception as its `__cause__`. `published` says whether the request may have
left: `False` means it failed before publishing and is safe to call again;
`True` means the method may have run, as with `ServerLostError`.

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

### Call without blocking (asyncio):
`client.aio` has the same calls, to `await`. Calls share the client's one
response queue, so any number can wait at once:
```python
sentiment = await client.aio.call("analyze-sentiment", request, Sentiment)

results = await asyncio.gather(*(
    client.aio.call("analyze-sentiment", TextRequest(r), Sentiment) for r in reviews
))
```
They raise the same errors as a blocking call, `TimeoutError` included
(AnyCall's, not asyncio's).

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
    ...  # the request queue already had >= 100 waiting requests; not submitted
```

A client-wide default can be set instead of passing `max_queue_depth` on every call:
```python
client = AnyCall.client(redis_uri, default_max_queue_depth=100)
client.set_default_max_queue_depth(200)  # change it later
client.get_default_max_queue_depth()     # -> 200
```

### Check the current backlog:
```python
depth = client.get_queue_depth("analyze-sentiment")  # LLEN of the request queue
```

## Configuration

```python
from datetime import timedelta

# Custom timeout
client = AnyCall.client(redis_uri, timeout=timedelta(seconds=60))

# Custom timeout and a default queue-depth limit for every call
client = AnyCall.client(
    redis_uri,
    timeout=timedelta(seconds=60),
    default_max_queue_depth=100,
)
```

By default a call waits for its response with no limit (`timedelta(0)`).
