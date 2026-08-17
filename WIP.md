# Work in progress

## Detached calls and consumer handlers

`call` is the simple path: publish, block, get the result. **Detached calls**
split that into two steps, so the code that *starts* a call and the code that
*collects* it don't have to be the same — or even run in the same process.

- `detached_call(name, req)` publishes the request and returns a **call id**
  right away. A worker can begin running it immediately; the caller moves on
  without blocking.
- `attach_call(id, Type)` takes that id, finds the call, and blocks until the
  result is ready (returning instantly if it already is).

Because the id is just a string, you can store it, hand it to another service,
or fan out many calls and attach to them later.

A result that no client ever attaches to would otherwise be lost when it
expires in Redis. `@Consumer("name")` is the safety net: the server invokes
it for any detached call whose result went uncollected, handing back the
original request (and the computed result) so you can persist, retry, or alert
instead of silently dropping the work.

### Java

**Client (detached / attach)**
```java
public class Application {
    public static void main(String[] args) {
        String redisUri = "redis://localhost:16379";
        AnyCallClient anyCall = AnyCall.client(redisUri);

        TextRequest req = new TextRequest("This is great!");

        // Fire the call — returns immediately with a handle, doesn't block
        String callId = anyCall.detachedCall("analyze-sentiment", req);
        System.out.println(callId); // e.g. "9f2c1e7a-..."

        // Later — same process or another service — claim it and wait for the result
        Sentiment sentiment = anyCall.attachCall(callId, Sentiment.class);
        System.out.println(sentiment);
    }
}
```

**Server (with consumer handler)**
```java
public class SentimentAnalyzer {
    @Supply("analyze-sentiment")
    public Sentiment analyzeSentiment(AnycallContext ctx, TextRequest req) {
        return new Sentiment(req.text(), "positive");
    }

    // Fires when a detached call's result is never attached/collected by a client
    @Consumer("analyze-sentiment")
    public void onLostSentiment(TextRequest req, Sentiment result) {
        // persist, retry, or alert instead of dropping the work
        System.out.println("Uncollected: " + req.text() + " -> " + result.label());
    }
}
```

### Python

**Client (detached / attach)**
```python
client = AnyCall.client("redis://localhost:16379")

# Fire the call — returns immediately with a handle, doesn't block
call_id = client.detached_call("analyze-sentiment", TextRequest(text="This is great!"))
print(call_id)  # "9f2c1e7a-..."  — store it, pass it around, attach later

# Later — same process or another service — claim it and wait for the result
sentiment = client.attach_call(call_id, Sentiment)
print(sentiment)  # Sentiment(text="This is great!", label="positive")
```

**Server (with consumer handler)**
```python
from anycall import AnyCall, AnycallContext, supply, consumer

class SentimentAnalyzer:
    @supply("analyze-sentiment")
    def analyze_sentiment(self, ctx: AnycallContext, req: TextRequest) -> Sentiment:
        return Sentiment(text=req.text, label="positive")

    # Fires when a detached call's result is never attached/collected by a client
    @consumer("analyze-sentiment")
    def on_lost_sentiment(self, req: TextRequest, result: Sentiment):
        # nobody attached to collect this — persist, retry, or alert
        print(f"Uncollected: {req.text} -> {result.label}")
```

## Smart cross-implementation test matrix

A harness that discovers `implementations/<lang>/` automatically and runs a
shared scenario suite (call, errors, timeouts, backpressure, detached/attach)
across every client × server language pair — a pass/fail grid instead of
manually-written interop tests per pair.

"Smart" means skipping pairs where neither side changed: with languages
A, B, and C, a change to A only needs (A×B, A×C, A×A) re-run — B×C
is untouched by the change and can be skipped.

## P2P calls

Redis becomes discovery-only. The server provides anycall a function that
resolves its own reachable address; the client looks that up via Redis, then
the request/response payload travels directly between them, never through
Redis. The client doesn't need to publish anything — it dials out and gets
the response on the same connection.

```java
// Server: advertises where it can be reached
AnyCallServer server = AnyCall.server(redisUri)
    .p2p(() -> new InetSocketAddress("10.0.0.5", 7000));
server.register(new SentimentAnalyzer());
server.start();

// Client: looks up the address via Redis, then talks to the server directly
AnyCallClient anyCall = AnyCall.client(redisUri);
Sentiment sentiment = anyCall.p2pCall("analyze-sentiment", req, Sentiment.class);
```
