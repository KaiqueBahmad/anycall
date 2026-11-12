# AnyCall Library

Redis-based library for RPC in Java. Provides a framework for communication between applications through Redis.
Call functions across Java services using Redis, with no `.proto` files, exposed ports, or extra service plumbing to maintain.

## Overview

AnyCall is a framework that allows Java applications to communicate asynchronously through Redis, using Redis Lists as the message transport mechanism.

## Main Components

### Core
- **AnyCall** - Main library interface
- **AnyCallClient** - Client for calling methods on remote suppliers
- **AnyCallServer** - Server for registering and executing methods

### Publisher
- **AnyCallPublisher** - Publishes messages/requests
- **AnycallQueues** - Manages message queues

### Annotation
- **Supply** - Annotation to mark methods as supply

### Models
- **AnyCallRequest** - RPC request model
- **AnyCallResponse** - RPC response model

## Build

```bash
./mvnw clean install
```

This will compile and install the library in the local Maven repository.

## Basic Usage

1. Implement a supplier using the `@Supply` annotation
2. Configure and start the `AnyCallServer`
3. Use `AnyCallClient` to call methods remotely

See `example-supplier` and `example-consumer` for practical examples.

## Dependencies

- Redis
- Java 17+

## Configuration

Clients and servers are configured through the `AnyCall` factory:

```java
// Wait up to 30s for each response (the default, Duration.ZERO, waits with no limit)
AnyCallClient client = AnyCall.client(redisUri, Duration.ofSeconds(30));

// Cap the whole server at 16 requests at a time, across every method
AnyCallServer server = AnyCall.server(redisUri, 16);
```

See [USAGE.md](../USAGE.md) for every option.
