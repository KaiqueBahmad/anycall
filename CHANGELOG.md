# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

### Added
- `call()` now fails fast with `NoServerAvailableError` (Java and Python) if no server has heartbeated recently, instead of queueing the request and waiting out the full timeout with nothing around to pop it. Checked against the same `anycall:servers:alive` registry and TTL the heartbeat uses, before the request is published
- A request whose server dies mid-processing is failed back to its client with a new `ServerLostError` (a `PublishError`, carrying the lost server's id) about 8–10s after the crash, instead of waiting out the whole timeout. Servers record each request they take in `anycall:inflight`, and any other live server cleans up after a dead one. The error response carries a `lostServer` field, only on these responses; clients from before this release can't parse it
- With no other server alive to notice, a waiting client fails back its dead server's requests itself, 30–60s after the crash: calls wait for their response in 30s slices, and once a whole client has gone 30s without a sign of a live server (a response, or a call finding one alive before publishing), one of its calls does the same cleanup a server would. The Java client opens a short-lived extra connection for it
- Clients publish on `anycall:wake:<method>` after pushing a request, so idle servers take it right away
- Visualizer: "In flight" panel and a "listening" column (servers subscribed to the method's wake channel)

### Changed
- Servers take requests with a Lua script that pops the request and records it as in flight atomically, instead of `BRPOP`; idle servers wait for a wake message, falling back to looking at their queues every second. Servers now hold four Redis connections
- A saturated server takes its next request as soon as a slot frees up, instead of sleeping a fixed 1s
- Calls now wait for their response with no limit by default (Java and Python), instead of 30s
- The liveness heartbeat now runs as a Lua script that reads Redis's own clock (`TIME`) for both the `ZADD` score and the `ZREMRANGEBYSCORE` cutoff, instead of each host's clock — clock skew between servers can no longer prune a live server or keep a dead one registered. Still one round trip per tick, one key, Cluster-compatible. The visualizer also reads `TIME` to compute each server's age

### Fixed
- Python client calls longer than 5s no longer fail with `TimeoutError` regardless of the configured timeout (redis-py 8's new 5s default socket timeout)
- Java client calls longer than 60s no longer fail with `TimeoutError` regardless of the configured timeout (Lettuce's default command timeout), and sub-second timeouts no longer round down to waiting forever

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
