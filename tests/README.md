# AnyCall Integration Tests

Integration and end-to-end tests for the AnyCall RPC framework across multiple languages.

## Structure

- `python/` - Python integration tests
- Java integration tests live at `implementations/java/tests/` (part of the Java Maven reactor)

## Running All Tests

### Prerequisites

- Redis 7.0+ running on `localhost:6379` (or set `REDIS_URI` env var)
- Java 17+ (for Java tests)
- Python 3.9+ (for Python tests)

### Run Both Test Suites

```bash
# From repo root
docker-compose up redis -d  # Start Redis

# Java tests
cd implementations/java/tests && mvn clean test

# Python tests
cd tests/python && pytest

# Stop Redis
docker-compose down
```

### Run Individual Test Suites

See `java/README.md` or `python/README.md` for language-specific instructions.

## Environment Variables

- `REDIS_URI` - Redis connection URI
  - Default: `redis://localhost:6379`
  - Example: `redis://redis-host:6380`

## CI/CD Integration

These tests are meant to be run in CI/CD pipelines to validate both implementations before releases. Update `.github/workflows/test.yml` to include the test suites.

## Adding New Tests

1. **Java:** Add test classes to `java/src/test/java/dev/kaiquebt/anycall/test/`
2. **Python:** Add test files to `python/src/` following pytest naming convention

Both should follow their respective language best practices and include integration with running Redis instances.
