# AnyCall Library

Redis-based library for RPC in Python. Provides a framework for communication between applications through Redis Streams.

## Overview

AnyCall is a framework that allows Python applications to communicate asynchronously through Redis, using Redis Streams as the message transport mechanism.

## Main Components

### Core
- **AnyCall** - Main library interface
- **AnyCallClient** - Client for calling methods on remote suppliers
- **AnyCallServer** - Server for registering and executing methods
- **RedisStreamAdapter** - Redis Streams adapter

### Configuration
- **AnycallProperties** - Configuration properties for the library
- **supply** - Decorator to mark methods as supply

### Models
- **AnyCallRequest** - RPC request model
- **AnyCallResponse** - RPC response model

## Build

```bash
uv sync
```

This will install the library and its dependencies in the workspace.

## Basic Usage

1. Implement a supplier using the `@supply` decorator
2. Configure and start the `AnyCallServer`
3. Use `AnyCallClient` to call methods remotely

See `example-supplier` and `example-consumer` for practical examples.

## Dependencies

- Redis
- Python 3.9+

## Configuration

Configure properties through `AnycallProperties`:

```python
from datetime import timedelta
from anycall import AnyCall

props = AnycallProperties(
    timeout=timedelta(seconds=30),
    metrics_enabled=True
)
```

Or use the defaults:

```python
from anycall import AnyCall

client = AnyCall.client("redis://localhost:6379")
```
