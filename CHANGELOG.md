# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [0.4] - 2026-09-04

### Added
- Heartbeats now travel on their own channel: a dedicated thread and a dedicated Redis connection, separate from the queue-reading and request/response-writing ones (three connections in total, still regardless of method count or configured concurrency) — a server with many in-flight requests no longer delays draining its queues to heartbeat, and heartbeating never stalls a response write
- Every heartbeat tick — the server's own key plus one per in-flight request — is now written in a single pipelined round trip instead of one `SET` per key (Java queues them on Lettuce's async API and flushes once, Python uses `pipeline(transaction=False)`); no `MULTI`/`EXEC` is used, since the keys are independent and skipping it keeps this compatible with Redis Cluster

### Changed
- AnyCall no longer uses Redis Streams; request and response queues (`anycall:requests:<method>`, `anycall:responses:<requestId>`) are now plain Redis Lists, using `LPUSH`/`BRPOP` instead of `XADD`/`XREADGROUP`/`XREAD` — consumer groups, `XACK`, and `XDEL` are gone entirely
- `getQueueDepth`/`maxQueueDepth` (`LLEN`) no longer counts requests currently being processed, only requests not yet popped by a worker — previously (`XLEN`) it included both, since Stream entries stuck around until `XDEL` ran after processing finished

## [0.3] - 2026-08-15

### Added
- Heartbeat keys split into `servers:` and `requests:` sub-namespaces (`anycall:heartbeat:servers:<serverId>`, `anycall:heartbeat:requests:<requestId>`), replacing the single flat per-server key
- The main read loop now also heartbeats every in-flight request id alongside the server's own heartbeat, on the same tick

### Changed
- Server heartbeat key no longer includes the consumer group name
- The server now reads with `XREADGROUP ... NOACK`, so messages no longer enter the consumer group's PEL; the now-unnecessary `XACK` calls were removed

## [0.2] - 2026-08-13

### Added
- Raw calls (`rawCall` / `raw_call`)
- Typed exception hierarchy (`AnyCallError` in Python, matching exceptions in Java)
- `AnycallContext` parameter exposing request id and channel name to handlers
- Queue depth introspection
- Configurable concurrency for suppliers
- Supplier heartbeats
- Automatic stream entry cleanup after message processing
- camelCase field serialization for cross-language interop

### Changed
- Renamed `@Supply`'s `value` element to `methodName`
- Standardized health file location to `/run/anycall`

### Java
- **0.2.2** (2026-08-14): Fixed the supplier erroring out on startup when no consumer had ever called its method yet — `XGROUP CREATE` now uses `MKSTREAM`, and a failed group-creation attempt is retried instead of being marked as done forever
- **0.2.1** (2026-08-13): Bumped `central-publishing-maven-plugin` from 0.6.0 to 0.11.0 to fix a deployment failure (`UnrecognizedPropertyException` on the API's new `warnings` field)

## [0.1] - 2026-06-14

### Added
- Initial public release of AnyCall RPC framework
- Full-duplex Redis-based communication protocol
- Type-safe calls
- Supplier notation
- Built-in type registry with Jackson serialization

### Java
- **0.1.1** (2026-06-14): Release to validate CI/CD pipeline (no code changes)
- **0.1.0** (2026-06-14): First Maven Central release
  - Java 17+ module system support
  - Lettuce Redis client integration
  - JUnit 5 test framework

### Python
- **0.1.3** (2026-06-14): Release to validate CI/CD pipeline (no code changes)
- **0.1.0** (TBD): Pending initial PyPI release
  - Python 3.10+ support
  - redis-py client integration
  - pytest test framework
