# anycall

[![PyPI](https://img.shields.io/pypi/v/anycall-py)](https://pypi.org/project/anycall-py/)
[![Maven Central](https://img.shields.io/maven-central/v/dev.kaiquebt.anycall/anycall)](https://central.sonatype.com/artifact/dev.kaiquebt.anycall/anycall)
![Python](https://img.shields.io/pypi/pyversions/anycall-py)
![License](https://img.shields.io/github/license/KaiqueBahmad/anycall)
![Stars](https://img.shields.io/github/stars/KaiqueBahmad/anycall)

Call functions across services written in different languages, using only the
Redis you already have.

A server registers a function under a name. A client calls that name and gets
the result back, as if the function were local. Redis sits in between, so
there are no `.proto` files, no code generation and no ports to open between
services, and every server that registers the same name shares its load.

## Example: serve in Python, call from Java

**Server (Python)**
```python
from dataclasses import dataclass
from sentence_transformers import SentenceTransformer
from anycall import AnyCall, AnyCallContext, supply

@dataclass
class EmbedRequest:
    text: str

@dataclass
class Embedding:
    vector: list[float]

class Embedder:
    def __init__(self):
        self.model = SentenceTransformer("all-MiniLM-L6-v2")

    @supply("embed")
    def embed(self, ctx: AnyCallContext, req: EmbedRequest) -> Embedding:
        return Embedding(vector=self.model.encode(req.text).tolist())

server = AnyCall.server("redis://localhost:16379")
server.register(Embedder())
server.start()
```

**Client (Java)**
```java
record EmbedRequest(String text) {}
record Embedding(float[] vector) {}

AnyCallClient client = AnyCall.client("redis://localhost:16379");

Embedding embedding = client.call("embed", new EmbedRequest("wireless headphones"), Embedding.class);
```

The two sides agree on the method name and on the JSON field names, nothing
else, and both use only the [payload types](#payload-types). Either language
can be the server or the client.

## Install

| | | |
|---|---|---|
| **Python** 3.10+ | `pip install anycall-py` (imported as `anycall`) | [Usage](implementations/python/USAGE.md) |
| **Java** 17+ | `dev.kaiquebt.anycall:anycall` | [Usage](implementations/java/USAGE.md) |
| **Spring Boot** 3.5 or 4 | `dev.kaiquebt.anycall:anycall-spring` | [Usage](integrations/spring/README.md) |

You need a Redis 5.0 or later.

→ [Installation guide](INSTALLATION.md): Maven snippets, building from source
and troubleshooting.

## The same thing in each language

<details>
<summary><b>Java</b></summary>

```java
public class Embedder {
    @Supply(methodName = "embed")
    public Embedding embed(AnyCallContext ctx, EmbedRequest req) {
        return new Embedding(model.embed(req.text()));
    }
}

// Server
AnyCallServer server = AnyCall.server("redis://localhost:16379");
server.register(new Embedder());
server.start();

// Client
AnyCallClient client = AnyCall.client("redis://localhost:16379");
Embedding embedding = client.call("embed", new EmbedRequest("wireless headphones"), Embedding.class);
```

</details>

<details>
<summary><b>Python</b></summary>

```python
class Embedder:
    @supply("embed")
    def embed(self, ctx: AnyCallContext, req: EmbedRequest) -> Embedding:
        return Embedding(vector=self.model.encode(req.text).tolist())

# Server
server = AnyCall.server("redis://localhost:16379")
server.register(Embedder())
server.start()

# Client
client = AnyCall.client("redis://localhost:16379")
embedding = client.call("embed", EmbedRequest(text="wireless headphones"), Embedding)
```

</details>

<details>
<summary><b>Spring Boot</b></summary>

```java
// Server: served while the application runs
@Component
@AnyCallSupplier
public class Embedder {
    @Supply(methodName = "embed")
    public Embedding embed(AnyCallContext ctx, EmbedRequest req) {
        return new Embedding(model.embed(req.text()));
    }
}

// Client: an interface whose methods call remote ones
@AnyCallApi
public interface EmbeddingApi {
    @Call("embed")
    Embedding embed(EmbedRequest request);
}
```

</details>

## What you get

- **Load balancing with no setup.** Start another server for a method and it
  begins taking requests. Nothing to register, no addresses to configure.
- **Blocking or not.** `client.call(...)` waits for the response;
  `client.async()` in Java returns a `CompletableFuture`, and `client.aio` in
  Python is awaited.
- **Limits on both sides.** A client sets a timeout and a queue limit, as its
  defaults or for one call. A server caps how many requests run at once, per
  method and across all of them. Both can change while running.
- **A dead server doesn't leave you waiting.** If a server dies mid-request,
  another server or the waiting client notices within about 10 seconds, and
  the call fails with a `ServerLostError` instead of running out its timeout.
- **Typed or raw.** Read a response into your own class, or take it as a map
  or dict when you have no model for it.
- **Isolation by prefix.** Clients and servers only see each other under the
  same key prefix, so several applications can share one Redis.

## Payload types

Arguments and results are limited on purpose to what JSON itself has, so a
type means the same in every language. A type has to be a `T`:

```
T = boolean
  | integer
  | number
  | string
  | array of T
  | map of string to T
  | record of fields, each a T
  | T or null
```

For anything else (bytes, enums, dates), you should declare a string or a
number and convert it in your code: a type outside these is rejected when a
method or a call declares it. → [The rules](LIBRARY.md#payload-types), and each type in
[Python](implementations/python/USAGE.md#payload-types) and
[Java](implementations/java/USAGE.md#payload-types).

## How it works

```
client ──LPUSH──▶ anycall:requests:<method> ──▶ any server that registered <method>
   ▲                                                       │
   └──BRPOP── anycall:responses:<client id> ◀──LPUSH───────┘
```

A request is a JSON message pushed onto the method's list. One server takes
it, runs the function and pushes the response onto the calling client's own
list. Servers send heartbeats, so a request held by a server that went silent
is failed back to its caller.

| | |
|---|---|
| The protocol on Redis that every implementation follows | [PROTOCOL.md](PROTOCOL.md) |
| How a library exposes it | [LIBRARY.md](LIBRARY.md) |
| What happens when a server dies mid-request | [docs/reaping.md](docs/reaping.md) |
| How a server takes a request without a crash losing it | [docs/taking-requests.md](docs/taking-requests.md) |

## When to use anycall

anycall fits when you have services in **different languages** that need to
call each other, and you'd rather not stand up a full RPC stack to do it.

- **Polyglot backends.** A Java service needs a function that lives in a
  Python service, or the other way around. Register the function on one side
  and call it by name from the other.

- **AI and inference workloads.** Orchestrate from a typed backend while the
  heavy work runs elsewhere: a Java service calls a Python inference worker,
  and requests spread across however many workers are running. Add GPU
  workers and they start receiving traffic.

- **You already run Redis.** anycall needs no new infrastructure: no message
  broker to provision, no service mesh, no ports to expose between services.

## When not to use anycall

- **You need the lowest latency or very high throughput.** Every call makes a
  round trip through Redis. A point-to-point RPC skips the hop.

- **A request must never be lost.** anycall is RPC, not a job queue. A request
  runs at most once: if its server dies mid-request, the caller gets a
  `ServerLostError` and decides whether to call again. Requests waiting in
  Redis are only as durable as your Redis.

- **You send large payloads or streams.** Requests and responses are JSON
  messages held in Redis memory. There is no streaming, so files, video and
  multi-megabyte bodies don't belong here.

- **You want a compiler-checked contract.** There is no schema file. A
  mismatch in a method name or a field name shows up at run time.

- **Callers are untrusted.** Anyone who can reach your Redis can call any
  method and read any payload. anycall is for services inside your own
  network, not for browsers, mobile apps or third parties.

- **You run Redis Cluster.** anycall doesn't work on Redis Cluster yet.

## Status

anycall is in `0.x`, and each minor version may break the previous one. A
client and a server can talk to each other, whatever their languages, when
they speak the same **protocol** version: the version of the release that
last changed what goes on Redis. 0.10 speaks protocol 0.9, so it works with
0.9. Each release's [changelog](CHANGELOG.md) section says which protocol it
speaks.

## License

See [LICENSE](LICENSE).
