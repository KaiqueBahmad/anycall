# anycall

Call functions across services written in different languages, using the
Redis you already have — no .proto files, no exposed ports, no per-service
plumbing to maintain.

A client publishes a request to Redis; any available server can pick it up,
run it, and return the result. Calls can be synchronous (block until the
response) or asynchronous (futures, promises, or callbacks), depending on
the language and runtime.

Because the broker sits in the middle — unlike point-to-point RPC such as
gRPC — you get automatic load balancing, horizontal scaling, and loose
coupling between services for free, with one consistent API across languages.

**Status:** Java and Python are under active development. The examples below
reflect the current target API.

## Exemplos de Uso

### Java

**Server**
```java
public class SentimentAnalyzer {
    @Supply("analyze-sentiment")
    public Sentiment analyzeSentiment(TextRequest req) {
        return new Sentiment(req.text(), "positive");
    }
}

public class Application {
    public static void main(String[] args) {
        String redisUri = "redis://localhost:6379";
        AnyCallServer server = AnyCall.server(redisUri);
        server.register(new ProductSupplier());
        server.start();
    }
}
```

**Client (explicit type)**
```java
public class Application {
    public static void main(String[] args) {
        String redisUri = "redis://localhost:6379";
        AnyCallClient anyCall = AnyCall.client(redisUri);

        TextRequest req = new TextRequest("This is great!");
        Sentiment sentiment = anyCall.call("analyze-sentiment", req, Sentiment.class);
        System.out.println(sentiment);
    }
}
```

**Client (registered type)**
```java
public class Application {
    public static void main(String[] args) {
        String redisUri = "redis://localhost:6379";
        AnyCallClient anyCall = AnyCall.client(redisUri);

        // Register type once
        anyCall.registerType("analyze-sentiment", Sentiment.class);

        // Then call without explicit type
        TextRequest req = new TextRequest("This is great!");
        Sentiment sentiment = anyCall.call("analyze-sentiment", req);
        System.out.println(sentiment);
    }
}
```

[→ See more](java/README.md)

---

### Python

**Server**
```python
from anycall import AnyCall, supply
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
    def analyze_sentiment(self, req: TextRequest) -> Sentiment:
        return Sentiment(text=req.text, label="positive")

if __name__ == "__main__":
    server = AnyCall.server("redis://localhost:6379")
    server.register(ProductSupplier())
    server.start()
```

**Client**
```python
from anycall import AnyCall
from dataclasses import dataclass

@dataclass
class TextRequest:
    text: str

client = AnyCall.client("redis://localhost:6379")
sentiment = client.call(
    "analyze-sentiment",
    TextRequest(text="This is great!")
)
print(sentiment)  # Returns dict: {"text": "This is great!", "label": "positive"}
```

[→ Ver mais](python/README.md)
