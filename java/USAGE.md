# AnyCall Java Usage Guide

## How to Use as Supplier (Server)

1. **Define a class with methods annotated with `@Supply`:**
```java
public class SentimentAnalyzer {
    @Supply("analyze-sentiment")
    public Sentiment analyzeSentiment(TextRequest req) {
        return new Sentiment(req.getText(), "positive");
    }
}
```

2. **Register and start the server:**
```java
String redisUri = System.getenv("REDIS_URI");
AnyCallServer server = AnyCall.server(redisUri);
server.register(new ProductSupplier());
server.start();
```

## How to Use as Consumer (Client)

### Call with explicit type:
```java
AnyCallClient client = AnyCall.client("redis://localhost:6379");
Sentiment sentiment = client.call("analyze-sentiment", request, Sentiment.class);
```

### Call with registry (register types once):
```java
AnyCallClient client = AnyCall.client("redis://localhost:6379");
client.registerType("analyze-sentiment", Sentiment.class);

// Then, calls without type:
Sentiment sentiment = client.call("analyze-sentiment", request);
```

### Call without model (returns Map):
```java
Map<String, Object> response = client.callRaw("analyze-sentiment", request);
```

## Configuration

```java
// Custom timeout
AnyCallClient client = AnyCall.client(redisUri, Duration.ofSeconds(60));

// With metrics
AnyCallClient client = AnyCall.client(redisUri, true);

// Both
AnyCallClient client = AnyCall.client(redisUri, Duration.ofSeconds(60), true);
```
