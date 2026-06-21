# AnyCall Python Integration Tests

Integration tests for the AnyCall Python implementation.

## Prerequisites

- Python 3.9+
- Redis 7.0+
- uv (recommended) or pip

## Installation

```bash
# Using uv (recommended)
uv sync

# Or using pip
pip install -e .
```

## Running Tests

```bash
# Run all tests
pytest

# Run with coverage report
pytest --cov=. --cov-report=html

# Run specific test file
pytest src/test_basic_integration.py -v

# Run tests by marker
pytest -m unit        # Unit tests only
pytest -m integration # Integration tests only
pytest -m "not slow"  # Skip slow tests
```

## Environment Variables

- `REDIS_URI` - Redis connection URI (default: `redis://localhost:6379`)

## Test Structure

- `src/test_*.py` - Test files following pytest naming convention

## Adding New Tests

1. Create a new test file in `src/` following pytest naming convention
2. Use `@pytest.mark` decorators for categorization:
   - `@pytest.mark.unit` - Unit tests
   - `@pytest.mark.integration` - Integration tests requiring Redis
   - `@pytest.mark.slow` - Slow tests
3. Run `pytest` to execute

## Test Markers

- `unit` - Unit tests (default)
- `integration` - Integration tests requiring external services
- `slow` - Slow tests

## Notes

- Integration tests require a running Redis instance
- Set `REDIS_URI` environment variable if using non-default Redis config
- Use `pytest.skip()` to gracefully skip tests when dependencies are unavailable
