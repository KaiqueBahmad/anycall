# AnyCall Library

Redis-based library for RPC in Java. Provides a framework for communication between applications through Redis Streams.

## Overview

AnyCall is a framework that allows Java applications to communicate asynchronously through Redis, using Redis Streams as the message transport mechanism.

## Main Components

### Core
- **AnyCall** - Main library interface
- **AnyCallClient** - Client for calling methods on remote suppliers
- **AnyCallServer** - Server for registering and executing methods
- **RedisStreamAdapter** - Redis Streams adapter

### Publisher
- **AnyCallPublisher** - Publishes messages/requests
- **AnycallQueues** - Manages message queues

### Configuration
- **AnycallProperties** - Configuration properties for the library
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

Configure properties through `AnycallProperties`:

```java
AnycallProperties props = new AnycallProperties(
    Duration.ofSeconds(30),  // timeout
    true                      // metricsEnabled
);
```

Or use the defaults:

```java
AnycallProperties props = new AnycallProperties();
```
