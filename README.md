# anycall

[![PyPI](https://img.shields.io/pypi/v/anycall-py)](https://pypi.org/project/anycall-py/) 
![Python](https://img.shields.io/pypi/pyversions/anycall-py)
![License](https://img.shields.io/github/license/KaiqueBahmad/anycall)
![Stars](https://img.shields.io/github/stars/KaiqueBahmad/anycall)

> 🚧 **Some features are still work in progress.** See [WIP.md](WIP.md) for details.

Call functions across services written in different languages, using only the
Redis you already have.

A client publishes a request to Redis; any available server can pick it up,
run it, and return the result. Calls can be **synchronous** (block until the
response) or **detached** — fire the call, get back an id, and attach to it
later (even from a different client) to collect the result.

Because the broker sits in the middle — unlike point-to-point RPC such as
gRPC — you get automatic load balancing, horizontal scaling, and loose
coupling between services, with one consistent API across languages.

**Status:** Java and Python are under active development. The examples below
reflect the current target API.

## Installation

Install AnyCall for your language:

**Python:** `pip install anycall-py` (import as `anycall`)  
**Java:** Add to `pom.xml` or build from `implementations/java/lib`

→ [See detailed installation guide](INSTALLATION.md)

## Usage Examples

### Java

**Server**
```java
public class SentimentAnalyzer {
    @Supply(methodName = "analyze-sentiment", maxConcurrency = 4) // optional, default: 1
    public Sentiment analyzeSentiment(AnycallContext ctx, TextRequest req) {
        return new Sentiment(req.text(), "positive");
    }
}

public class Application {
    public static void main(String[] args) {
        String redisUri = "redis://localhost:16379";
        AnyCallServer server = AnyCall.server(redisUri);
        server.register(new SentimentAnalyzer());
        server.start();
    }
}
```

**Client (explicit type)**
```java
public class Application {
    public static void main(String[] args) {
        String redisUri = "redis://localhost:16379";
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
        String redisUri = "redis://localhost:16379";
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

[→ See more](implementations/java/README.md)

---

### Python

**Server**
```python
from anycall import AnyCall, AnycallContext, supply
from dataclasses import dataclass

@dataclass
class TextRequest:
    text: str

@dataclass
class Sentiment:
    text: str
    label: str

class SentimentAnalyzer:
    @supply("analyze-sentiment", max_concurrency=4)  # optional, default: 1
    def analyze_sentiment(self, ctx: AnycallContext, req: TextRequest) -> Sentiment:
        return Sentiment(text=req.text, label="positive")

if __name__ == "__main__":
    server = AnyCall.server("redis://localhost:16379")
    server.register(SentimentAnalyzer())
    server.start()
```

**Client (with explicit type)**
```python
from anycall import AnyCall
from dataclasses import dataclass

@dataclass
class TextRequest:
    text: str

@dataclass
class Sentiment:
    text: str
    label: str

client = AnyCall.client("redis://localhost:16379")
sentiment = client.call(
    "analyze-sentiment",
    TextRequest(text="This is great!"),
    Sentiment
)
print(sentiment)  # Returns Sentiment object
```

**Client (returns dict)**
```python
response = client.raw_call("analyze-sentiment", TextRequest(text="This is great!"))
print(response)  # Returns dict: {"text": "This is great!", "label": "positive"}
```

[→ See more](implementations/python/README.md)

## When to use anycall

anycall fits when you have services in **different languages** that need to
call each other, and you'd rather not stand up a full RPC stack to do it.

- **Polyglot backends.** A Java service needs a function that lives in a
  Python service (or vice-versa). No shared `.proto`, no codegen step — register
  the function on one side, call it by name from the other.

- **Heterogeneous AI / inference workloads.** Orchestrate from a typed backend
  while the heavy work runs elsewhere: a Java or Node service calls a Python
  inference worker, and the broker spreads requests across however many workers
  are running. Add GPU workers and they start receiving traffic automatically —
  no client changes.

- **You already run Redis.** If Redis is already in your stack, anycall needs
  no new infrastructure. No message broker to provision, no service mesh, no
  ports to expose between services.

- **Scaling workers should be trivial.** Because the broker sits in the middle,
  running N copies of a server load-balances for free — Redis hands each request
  to exactly one available worker. Scale down to zero and back up; clients don't
  notice.

## How it compares

|                         | anycall            | gRPC              | Raw Redis / broker | Celery            |
|-------------------------|--------------------|-------------------|--------------------|-------------------|
| Cross-language          | Yes                | Yes               | Yes (DIY)          | Limited           |
| Schema / codegen step   | None               | `.proto` required | None               | None              |
| Topology                | Broker (decoupled) | Point-to-point    | Broker             | Broker            |
| Built-in load balancing | Yes (via broker)   | Needs LB / mesh   | DIY                | Yes               |
| Extra infrastructure    | Reuses Redis       | —                 | Redis              | Broker + backend  |
| Plumbing you write       | None               | Service stubs     | All of it          | Task definitions  |
