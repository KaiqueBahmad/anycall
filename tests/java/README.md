# AnyCall Java Integration Tests

Integration tests for the AnyCall Java implementation.

## Prerequisites

- Java 17+
- Maven 3.8+
- Redis 7.0+

## Running Tests

```bash
# Run all tests
mvn clean test

# Run with specific test class
mvn test -Dtest=BasicIntegrationTest

# Run with coverage
mvn clean test jacoco:report
```

## Environment Variables

- `REDIS_URI` - Redis connection URI (default: `redis://localhost:6379`)

## Test Structure

- `src/test/java/dev/kaiquebt/anycall/test/` - Integration test classes

## Adding New Tests

1. Create a new test class in `src/test/java/dev/kaiquebt/anycall/test/`
2. Extend or follow the pattern from `BasicIntegrationTest`
3. Use `@Test` annotation from JUnit 5
4. Run `mvn test` to execute

## Notes

- All tests require a running Redis instance
- Set `REDIS_URI` environment variable if using non-default Redis config
- Tests are run during `mvn clean install` in the parent pom.xml
