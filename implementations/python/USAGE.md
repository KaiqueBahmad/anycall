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

Pass `ServerOptions` to `AnyCall.server(...)` for a server-wide cap across every
registered method combined:
```python
from anycall import ServerOptions

server = AnyCall.server("redis://localhost:16379", ServerOptions(max_concurrency=16))
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

### Settings:
`CallOptions` holds a call's timeout and queue limit; `None` means no limit.
Given to `AnyCall.client`, they're the defaults of every call, and what they
leave out has no limit; passed to one call, they replace the client's, and
what they leave out stays the client's. They can be made once and reused:
```python
from datetime import timedelta
from anycall import CallOptions
from anycall.exceptions import QueueFullError

client = AnyCall.client(redis_uri, CallOptions(timeout=timedelta(seconds=60), max_queue_depth=100))
try:
    sentiment = client.call("analyze-sentiment", request, Sentiment)
except QueueFullError:
    ...  # the request queue already had >= 100 waiting requests; not submitted

urgent = CallOptions(timeout=timedelta(seconds=5), max_queue_depth=None)
sentiment = client.call("analyze-sentiment", request, Sentiment, urgent)
await client.aio.call("analyze-sentiment", request, Sentiment, urgent)
```
A timeout must be positive and a queue limit at least 1; anything else is a
`ValueError` when the options are made. With no `CallOptions`, a call waits
with no limit and is published however full its queue is.

The client's defaults can change while it runs; what the options set replaces
the client's, what they leave out stays. Calls already waiting keep theirs:
```python
client.update_defaults(CallOptions(max_queue_depth=200))  # only the queue limit
client.defaults  # CallOptions(timeout=datetime.timedelta(seconds=60), max_queue_depth=200)
```

### Check the current backlog:
```python
depth = client.queue_depth("analyze-sentiment")  # LLEN of the request queue
```
