# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [0.1] - 2026-06-14

Contract version: **0.1** (synchronized API across all implementations)

### Added
- Initial public release of AnyCall RPC framework
- Full-duplex Redis-based communication protocol
- Type-safe call and cast APIs (typed and raw variants)
- Consumer handler pattern (previously "dead-letter")
- Request timeout and retry mechanisms
- Built-in type registry with Jackson serialization

### Java
- **0.1.0** (2026-06-14): First Maven Central release
  - Java 17+ module system support
  - Lettuce Redis client integration
  - JUnit 5 test framework

### Python
- **0.1.0** (TBD): Pending initial PyPI release
  - Python 3.8+ support
  - redis-py client integration
  - pytest test framework

---

## Release Strategy

### Version Format
- **Contract (X.Y)**: Synchronized across all languages
  - Guarantees: same API, same behavior, 100% compatibility
  - Released via tag: `vX.Y`

- **Patch (Z)**: Independent per language
  - Bug fixes, minor improvements specific to one implementation
  - Released via tag: `{language}-vX.Y.Z` (e.g., `java-v0.1.1`, `python-v0.1.2`)

### Updating This Changelog

When releasing a new contract version (e.g., v0.2):
1. Add new `## [0.2] - YYYY-MM-DD` section at the top
2. List Added/Changed/Fixed for all languages
3. Add language-specific patch tables below

When releasing a language-specific patch (e.g., `java-v0.1.1`):
1. Update the Java section under the current contract version
2. Add `- **0.1.1** (YYYY-MM-DD): Fix description`
3. Do NOT create a new contract section
