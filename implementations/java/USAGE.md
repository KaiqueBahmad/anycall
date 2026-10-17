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

Pass `maxConcurrency` to `AnyCall.server(...)` for a server-wide cap across every
registered method instead:

```java
AnyCallServer server = AnyCall.server(redisUri, false, 16);
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
client notices on its own once it has had no response for 30s, so the error
comes 30–60s after the crash. The request is not retried, and may have
partially run.

A `TimeoutError` says nothing about the server: it may be slow, may never have
taken the request, or may have been lost too recently to be noticed.

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

### Fail fast if no server is available:
```java
try {
    Sentiment sentiment = client.call("analyze-sentiment", request, Sentiment.class);
} catch (NoServerAvailableError e) {
    // no server has heartbeated recently; not submitted
}
```
Every call checks the heartbeat registry before publishing the request, the
same way a plain HTTP call would get connection-refused instead of hanging:
without this, a request sitting in an empty queue would just wait out the
full timeout with nothing to pop it. This only confirms *some* server is
alive, not that one of them supports the method being called.

## Configuration

```java
// Custom timeout
AnyCallClient client = AnyCall.client(redisUri, Duration.ofSeconds(60));

// With metrics
AnyCallClient client = AnyCall.client(redisUri, true);

// Both
AnyCallClient client = AnyCall.client(redisUri, Duration.ofSeconds(60), true);
```

By default a call waits for its response with no limit (`Duration.ZERO`).
