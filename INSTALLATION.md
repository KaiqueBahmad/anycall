# Installation Guide

## Quick Start

AnyCall is a polyglot RPC framework with implementations in **Java** and **Python**.

### Python

Install the Python library via pip:

```bash
pip install anycall-py
```

**Note:** The package name is `anycall-py`, but you import it as `anycall`:

```python
from anycall import AnyCall, supply
```

### Java

Add the Maven dependency to your `pom.xml`:

```xml
<dependency>
    <groupId>dev.kaiquebt.anycall</groupId>
    <artifactId>anycall</artifactId>
    <version>0.1.1</version>
</dependency>
```

Or build from source (multi-module Maven reactor):

```bash
cd implementations/java
mvn clean install
```

This installs the `anycall` library to your local Maven repository as
`dev.kaiquebt.anycall:anycall:0-SNAPSHOT`.

---

## Requirements

### Both Languages

- **Redis 7.0+** — Used for message transport via Redis Streams
- Running Redis instance (local or remote)

### Python

- Python 3.9+
- Dependencies installed automatically:
  - `redis>=5.0.0` — Redis client with Streams support
  - `dacite>=1.8.0` — Dataclass deserialization

### Java

- Java 17+
- Maven 3.8+
- Dependencies managed by Maven:
  - `lettuce-core` — Async Redis client
  - `jackson-databind` — JSON serialization
  - `junit-jupiter` — Testing framework (optional)

---

## Local Development Setup

### Python

```bash
# Clone and navigate to Python directory
cd implementations/python

# Install in development mode with dependencies
uv sync

# Or using pip
pip install -e .

# Run example
uv run python -m example_supplier.main
```

### Java

```bash
# Clone and navigate to the Java reactor root
cd implementations/java

# Build all modules (lib + examples)
mvn clean install

# Run the examples (compiles and executes via exec-maven-plugin)
./run-supplier.sh
./run-consumer.sh
```

---

## Redis via Docker Compose

The bundled `docker-compose.yml` provisions just the Redis broker that AnyCall
needs — the supplier/consumer apps run locally (see the build steps above):

```bash
# Start Redis
docker-compose up -d

# View logs
docker-compose logs -f

# Stop
docker-compose down
```

Services available:
- `redis` — Message broker, exposed on `localhost:6379`

---

## Verify Installation

### Python

```python
from anycall import AnyCall, supply

# Should import without error
print("AnyCall imported successfully!")

# Create a client
client = AnyCall.client("redis://localhost:6379")
print("Client created!")
```

### Java

```java
import dev.kaiquebt.anycall.core.AnyCall;
import dev.kaiquebt.anycall.core.AnyCallClient;

AnyCallClient client = AnyCall.client("redis://localhost:6379");
System.out.println("Client created!");
```

---

## Troubleshooting

### "ModuleNotFoundError: No module named 'anycall'"

You likely installed `anycall` instead of `anycall-py`. Uninstall and reinstall:

```bash
pip uninstall anycall
pip install anycall-py
```

### "Cannot connect to Redis"

Ensure Redis is running on `localhost:6379` (or set `REDIS_URI` environment variable):

```bash
# Start Redis locally
redis-server

# Or use Docker
docker run -d -p 6379:6379 redis:7-alpine

# Or point to remote Redis
export REDIS_URI="redis://your-redis-host:6379"
```

### Java compilation fails

Ensure you have Java 17+ and Maven 3.8+:

```bash
java -version
mvn -version
```

---

## Next Steps

After installation, see:

- **Python**: [implementations/python/USAGE.md](implementations/python/USAGE.md)
- **Java**: [implementations/java/USAGE.md](implementations/java/USAGE.md)
- **Root**: [README.md](README.md) for architectural overview
