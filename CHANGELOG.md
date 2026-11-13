# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

### Changed
- Redis 5.0 or later is enough; servers take with `BLMOVE` where Redis has it (6.2+)

### Fixed
- A server whose first heartbeat fails no longer starts taking requests: `start()` now raises, and can be called again
- A call whose request has an unknown or missing field now fails with a `RemoteException` when the server rejects it, instead of waiting forever
- Java: a request missing a field is rejected instead of running with that field as `null`
- Java: stopping a server waits for the requests it already took to finish and be answered, as Python does, instead of interrupting them after 5s
- Python docs no longer describe Redis Streams
- Python: messages are read by their camelCase field names only, as in Java
- A response with neither a payload nor an error fails with `SerializationError`
- Python: a typed call to a method that returned `None` returns `None` instead of failing
- A Redis failure during a call raises `BrokerError`, and a Redis that stops answering fails the call within 15s instead of hanging

### Removed
- The metrics flag on `AnyCall.client(...)` and `AnyCall.server(...)` (`metricsEnabled` in Java, `metrics_enabled` in Python)
- Java: the `AnycallProperties` class, which nothing read
- Visualizer: support for Redis Streams queues
- Java: the unused `AnyCallPublisher` and `ConnectionError`
- Python: `JSONDecodeError`; invalid JSON raises `SerializationError`, as in Java

## [0.6] - 2026-11-07

This release replaces the library's internals: how servers take requests,
how they track the ones they are processing, and how a crashed server is
detected and its requests failed back.

### Added
- `call()` fails right away with `NoServerAvailableError` when no server is alive, instead of waiting out its timeout
- When a server dies while processing a request, the client gets a `ServerLostError` within about 10s (up to 18s if no other server is alive), instead of waiting out its timeout
- Visualizer: "In flight" panel, with an estimate of when a dead server's requests will be failed back

### Changed
- A server crash can no longer lose a request it had just taken
- Servers open one Redis connection per method
- `max_concurrency` limits requests running at the same time, not requests taken; it can be exceeded by one waiting request per method
- A busy method takes its next request as soon as a slot frees, instead of after a fixed 1s sleep
- Calls wait for their response with no limit by default, instead of 30s
- Liveness uses Redis's clock instead of each host's, so clock differences between machines no longer make a live server look dead (or a dead one alive)

### Fixed
- Responses nobody reads now expire after 60s instead of staying in Redis forever
- Python: calls longer than 5s no longer fail with `TimeoutError` regardless of the configured timeout
- Java: calls longer than 60s no longer fail with `TimeoutError` regardless of the configured timeout, and timeouts under 1s no longer turn into waiting forever

### Breaking
- `ServerLostError` responses carry a new `lostServer` field that clients older than 0.6 can't parse

## [0.5] - 2026-09-26

### Added
- Server liveness registry: every server keeps its own entry fresh in the `anycall:servers:alive` sorted set (`ZADD` its id under the current timestamp every 2s, prune members older than 8s, refresh the key's TTL — one pipelined round trip per tick, no `MULTI`/`EXEC`). The period and TTL are hardcoded
- Server id exposed on the server (`getServerId()` in Java, `server_id` in Python) and logged on startup; it is now a plain UUID (no `server-` prefix)
- Visualizer: "Servers" panel now reads the `anycall:servers:alive` sorted set, and a new "always on top" button pins the window above the others
- Contract releases (`vX.Y` tags) now also create a GitHub Release with the jar and the Python wheel/sdist attached

### Changed
- `ChannelError` renamed to `PublishError` (Java and Python); `TimeoutError`, `QueueFullError` and (Java) `ConnectionError` now extend it
- `TimeoutError` now only carries the call id — `timeoutMs`/`timeout_ms` and the TTL timestamp were removed from it
- The heartbeat no longer does any cleanup on shutdown: a stopped server simply drops off the registry once its entry ages past the TTL

### Removed
- The per-key heartbeat system: servers no longer write `anycall:heartbeat:servers:<serverId>` or `anycall:heartbeat:requests:<requestId>` keys, and in-flight requests are no longer heartbeated
- Unused exceptions: `RecoverableCall`, `ChannelClosedError`, `WorkerUnavailableError`, `ValidationError`, `TypeMismatchError` (Java and Python), `JSONDecodeError` (Java) and `ConnectionError` (Python)

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
