# AnyCall Python Usage Guide

## How to Use as Supplier (Server)

1. **Define a class with methods decorated with `@supply`:**
```python
from anycall import AnyCallContext, supply
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
    def analyze_sentiment(self, ctx: AnyCallContext, req: TextRequest) -> Sentiment:
        return Sentiment(text=req.text, label="positive")
```

`@supply` accepts an optional `max_concurrency` (default `1`): how many requests for
that operation a single server instance may process at the same time.
```python
    @supply("analyze-sentiment", max_concurrency=4)
    def analyze_sentiment(self, ctx: AnyCallContext, req: TextRequest) -> Sentiment:
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

server.update_options(ServerOptions(max_concurrency=32))  # while it runs
```
Lowering the cap lets the requests already running finish; no new one runs
until fewer than the new cap do.

Each method's own cap can change the same way:
```python
server.methods                                    # ['analyze-sentiment', 'echo']
server.method("analyze-sentiment")                # MethodInfo(max_concurrency=4, running=2, declared=SupplyMethod(name='analyze-sentiment', ...))
server.method("analyze-sentiment").declared.max_concurrency  # as @supply says, whatever it is now
server.set_max_concurrency("analyze-sentiment", 8)
```

The same view of an object before registering it, checked the way `register`
checks it:
```python
from anycall import utils

utils.methods(SentimentAnalyzer())                          # ['analyze-sentiment']
utils.method(SentimentAnalyzer(), "analyze-sentiment")       # SupplyMethod(..., max_concurrency=4, request_type=TextRequest, response_type=Sentiment)
```

`close()` stops the server, as `stop()` does, then closes its Redis
connections; a closed server can't be started again. A server works with
`with`:
```python
with AnyCall.server(redis_uri) as server:
    server.register(SentimentAnalyzer()).start()
    ...
```

A method can also be served without a class, as a function under a name. Its
`SupplyMethod` gives what `@supply` and the method's signature would: the name,
`max_concurrency`, and request and response types:
```python
from anycall import SupplyMethod

server.register_method(SupplyMethod("shout", 4, str, str), lambda ctx, text: text.upper())
```

### Key prefix
Every key starts with `anycall` unless another prefix is given. A client and
a server see each other only under the same prefix, and it's fixed once they're
created:
```python
server = AnyCall.server(redis_uri, prefix="billing")
client = AnyCall.client(redis_uri, CallOptions(timeout=timedelta(seconds=30)), prefix="billing")
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

### Close the client:
```python
with AnyCall.client(redis_uri) as client:
    client.call("analyze-sentiment", request, Sentiment)
```
`close()` stops everything at once: calls still waiting fail with
`ClientClosedError`, as does any call made after, and the client's connections
and thread are gone when it returns. A request already published may still be
processed by a server; its response is dropped.
