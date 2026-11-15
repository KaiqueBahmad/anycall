# AnyCall Spring

Spring Boot auto-configuration for AnyCall: a client bean, a server that serves
your `@AnyCallSupplier` beans, and interfaces that call remote methods.

```xml
<dependency>
    <groupId>dev.kaiquebt.anycall</groupId>
    <artifactId>anycall-spring</artifactId>
    <version>0.10.0</version>
</dependency>
```

It brings `anycall` in. To take a fix of `anycall` before `anycall-spring` has
a release with it, declare `anycall` too, of the same contract (`X.Y`): their
versions may differ in the last number. With one of another contract, the
context fails at startup and says which to use.

Spring Boot 3.5 or 4, Java 17.

## Settings

```yaml
anycall:
  redis-url: redis://localhost:6379   # default
  prefix: anycall                     # default; clients and servers meet under the same one
  client:
    enabled: true                     # default
    timeout: 30s                      # left out: no limit
    max-queue-depth: 100              # left out: no limit
  server:
    enabled: true                     # default
    max-concurrency: 16               # server-wide; left out: none
    shutdown-timeout: 30s             # default; how long a close waits for running requests
```

## Serving methods

Annotate a bean with `@AnyCallSupplier` and its methods with `@Supply`, as
without Spring. They're served once the context has started. When it closes,
the server stops taking requests and finishes the ones already taken, for up to
`anycall.server.shutdown-timeout` (30s by default). Past that, the handlers
still running are interrupted and the close goes on. A handler that stops on
the interrupt fails its call with an error; one that ignores it keeps running,
but no longer holds up the close:

```java
@Component
@AnyCallSupplier
public class SentimentAnalyzer {
    @Supply(methodName = "analyze-sentiment", maxConcurrency = 4)
    public Sentiment analyze(AnycallContext ctx, TextRequest request) {
        return new Sentiment(request.text().contains("good") ? "positive" : "negative");
    }
}
```

Each `@Supply` method is called through the bean Spring hands out, so the
bean's advice (`@Transactional`, `@Timed`, security) runs as for any other
call. A proxy can't call a private or final method, so on a proxied bean
those fail the context at startup.

Two beans supplying the same method name fail the context at startup, which
then lists every such method and its beans: which one served it would depend
on the order beans come in.

No `@AnyCallSupplier` bean, no server. With `anycall.server.enabled: false`
there's no server either, and the suppliers that go unserved are logged.
Inject `AnyCallServer` to read or change it while it runs (`methods()`,
`method(name)`, `setMaxConcurrency`, `updateOptions`).

## Calling methods

Inject `AnyCallClient`, or declare an interface: each method calls the remote
method its `@Call` names, takes the request and returns the response. A method
with no argument sends a `null` request.

```java
@AnyCallApi
public interface SentimentApi {
    @Call("analyze-sentiment")
    Sentiment analyze(TextRequest request);

    @Call(value = "analyze-sentiment", timeout = "2s", maxQueueDepth = "none")
    CompletableFuture<Sentiment> analyzeAsync(TextRequest request);
}

@Service
public class Reviews {
    private final SentimentApi sentiment;

    public Reviews(SentimentApi sentiment) {
        this.sentiment = sentiment;
    }
}
```

### What a method returns

| Returns | Call |
|---|---|
| `T`, a class with no type parameters | waits, and reads the response into `T` |
| `JsonNode` | the same, as a tree |
| `Map<String, Object>` | a raw call: waits, and returns the response as a map |
| `void` | waits, and drops the response |
| `CompletableFuture<…>` of any of these | the same, without waiting (`Void` for `void`) |

Anything else, such as `Object`, `List<Foo>` or a raw `CompletableFuture`,
fails the context at startup, as do a method without `@Call` and one taking
more than the request.

### Settings

`timeout` and `maxQueueDepth` are written in place, or taken from
configuration with property placeholders (`${...}`, with an optional default),
resolved once when the context starts. SpEL (`#{...}`) isn't read. Left out or
empty, the client's apply; `none` lifts the limit:

```java
@Call(value = "analyze-sentiment", timeout = "2s", maxQueueDepth = "100")
Sentiment analyze(TextRequest request);

@Call(value = "analyze-sentiment",
      timeout = "${sentiment.timeout:2s}", maxQueueDepth = "${sentiment.max-queue:none}")
Sentiment analyzeConfigured(TextRequest request);
```

The method name may come from configuration the same way.

A timeout is a positive duration (`2s`, `500ms`, `PT30S`; a bare number is
milliseconds) and a queue limit at least 1. A value that doesn't resolve, or
isn't valid, fails the context at startup.

Default and static methods run as written; default ones may call the others.

Interfaces are found in the application's own packages. For others, add
`@EnableAnyCallApis(basePackages = "...")`.

## Your own beans

Define an `AnyCallClient` or `AnyCallServer` bean and yours is used.
