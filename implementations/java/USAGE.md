# AnyCall Java Usage Guide

## How to Use as Supplier (Server)

1. **Define a class with methods annotated with `@Supply`:**
```java
public class SentimentAnalyzer {
    @Supply(methodName = "analyze-sentiment")
    public Sentiment analyzeSentiment(AnycallContext ctx, TextRequest req) {
        return new Sentiment(req.text(), "positive");
    }
}
```

`@Supply` accepts an optional `maxConcurrency` (default `1`): how many requests for
this method a single server instance will process at the same time.

```java
@Supply(methodName = "analyze-sentiment", maxConcurrency = 4)
public Sentiment analyzeSentiment(AnycallContext ctx, TextRequest req) {
    return new Sentiment(req.text(), "positive");
}
```

Pass `ServerOptions` to `AnyCall.server(...)` for a server-wide cap across every
registered method instead:

```java
AnyCallServer server = AnyCall.server(redisUri, ServerOptions.DEFAULT.withMaxConcurrency(16));

server.updateOptions(ServerOptions.DEFAULT.withMaxConcurrency(32));   // while it runs
```
Lowering the cap lets the requests already running finish; no new one runs
until fewer than the new cap do.

Each method's own cap can change the same way:
```java
server.methods();                             // [analyze-sentiment, echo]
server.method("analyze-sentiment");           // MethodInfo[maxConcurrency=4, running=2, declared=SupplyMethod[name=analyze-sentiment, ...]]
server.method("analyze-sentiment").declared().maxConcurrency();   // as @Supply says, whatever it is now
server.setMaxConcurrency("analyze-sentiment", 8);
```

The same view of an object before registering it, checked the way `register`
checks it:
```java
AnycallUtils.methods(new SentimentAnalyzer());                          // [analyze-sentiment]
AnycallUtils.method(new SentimentAnalyzer(), "analyze-sentiment");      // SupplyMethod[..., maxConcurrency=4, requestType=class TextRequest, responseType=class Sentiment]
```

`close()` stops the server, as `stop()` does, then closes its Redis
connections; a closed server can't be started again. Servers are
`AutoCloseable`:
```java
try (AnyCallServer server = AnyCall.server(redisUri)) {
    server.register(new SentimentAnalyzer()).start();
    ...
}
```

### Key prefix
Every key starts with `anycall` unless another prefix is given. A client and
a server see each other only under the same prefix, and it's fixed once they're
created:
```java
AnyCallServer server = AnyCall.server(redisUri, "billing");
AnyCallClient client = AnyCall.client(redisUri, "billing", CallOptions.DEFAULT.withTimeout(Duration.ofSeconds(30)));
```

2. **Register and start the server:**
```java
String redisUri = System.getenv("REDIS_URI");
AnyCallServer server = AnyCall.server(redisUri);
server.register(new SentimentAnalyzer());
server.start();
```

### If a server dies mid-request

If a server crashes while processing a request, another live server notices
within ~8–10s and fails the request back: the client gets a `ServerLostError`
instead of waiting out its timeout. If no other server is alive, the waiting
client notices on its own at the end of its current 10s wait, so the error
comes 8–18s after the crash. The request is not retried, and may have
partially run.

A `TimeoutError` says nothing about the server: it may be slow, may never have
taken the request, or may have been lost too recently to be noticed.

How it works: [docs/reaping.md](../../docs/reaping.md).

### If Redis fails mid-call

If a Redis command fails during a call (the connection drops, Redis restarts
or stops answering for 15s), the call throws a `BrokerError`.
`isPublished()` says whether the request may have left: `false` means it
failed before publishing and is safe to call again; `true` means the method
may have run, as with `ServerLostError`.

## How to Use as Consumer (Client)

### Call with explicit type:
```java
AnyCallClient client = AnyCall.client("redis://localhost:16379");
Sentiment sentiment = client.call("analyze-sentiment", request, Sentiment.class);
```

### Call with registry (register types once):
```java
AnyCallClient client = AnyCall.client("redis://localhost:16379");
client.registerType("analyze-sentiment", Sentiment.class);

// Then, calls without type:
Sentiment sentiment = client.call("analyze-sentiment", request);
```

### Call without model (returns Map):
```java
Map<String, Object> response = client.rawCall("analyze-sentiment", request);
```

### Call without blocking:
`client.async()` has the same calls, returning a `CompletableFuture` instead of
the result. Calls share the client's one response queue, so any number can
wait at once without a thread each:
```java
CompletableFuture<Sentiment> future =
    client.async().call("analyze-sentiment", request, Sentiment.class);
future.thenAccept(s -> log.info("label: {}", s.label()));

List<CompletableFuture<Sentiment>> futures = reviews.stream()
    .map(r -> client.async().call("analyze-sentiment", new TextRequest(r), Sentiment.class))
    .toList();
CompletableFuture.allOf(futures.toArray(CompletableFuture[]::new)).join();
```
Errors complete the future exceptionally, wrapped in a `CompletionException`
as usual: `e.getCause()` is the same `TimeoutError`, `ServerLostError`, ...
a blocking call would throw.

### Settings:
`CallOptions` holds a call's timeout and queue limit. Given to
`AnyCall.client`, they're the defaults of every call, and what they leave out
has no limit; passed to one call, they replace the client's, and what they
leave out stays the client's. They're immutable: every `with` returns a copy,
so they can be made once and reused:
```java
AnyCallClient client = AnyCall.client(redisUri, CallOptions.DEFAULT
    .withTimeout(Duration.ofSeconds(60))
    .withMaxQueueDepth(100));   // QueueFullError past 100 waiting

CallOptions urgent = CallOptions.DEFAULT
    .withTimeout(Duration.ofSeconds(5))
    .withNoQueueLimit();
Sentiment s = client.call("analyze-sentiment", request, Sentiment.class, urgent);
client.async().call("analyze-sentiment", request, Sentiment.class, urgent);
```
A timeout must be positive and a queue limit at least 1; anything else is an
`IllegalArgumentException` when the options are made. With no `CallOptions`,
a call waits with no limit and is published however full its queue is.

The client's defaults can change while it runs; what the options set replaces
the client's, what they leave out stays. Calls already waiting keep theirs:
```java
client.updateDefaults(CallOptions.DEFAULT.withMaxQueueDepth(200));   // only the queue limit
client.defaults();   // CallOptions{timeout=PT1M, maxQueueDepth=200}
```

### Check the current backlog:
```java
long depth = client.getQueueDepth("analyze-sentiment");  // LLEN of the request queue
```

### Close the client:
```java
try (AnyCallClient client = AnyCall.client(redisUri)) {
    client.call("analyze-sentiment", request, Sentiment.class);
}
```
`close()` stops everything at once: calls still waiting fail with
`ClientClosedError`, as does any call made after, and the client's connections
and thread are gone when it returns. A request already published may still be
processed by a server; its response is dropped.
