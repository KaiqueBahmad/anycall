# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

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
