# Testing Guide for AnyCall Python Library

## Setup

Install development dependencies:

```bash
cd implementations/python
uv sync
```

## Running Tests

### Run all tests
```bash
pytest
```

### Run with coverage report
```bash
pytest --cov=anycall --cov-report=html
```

### Run specific test file
```bash
pytest src/anycall/test_client.py -v
```

### Run tests by marker
```bash
pytest -m unit        # Run unit tests only
pytest -m integration # Run integration tests only
```

### Run with verbose output
```bash
pytest -v
pytest -vv  # More verbose
```

## Test Structure

Tests are located in `src/anycall/test_*.py` files.

### Available Markers
- `@pytest.mark.unit` - Unit tests (default)
- `@pytest.mark.integration` - Integration tests requiring external services
- `@pytest.mark.slow` - Slow tests

## Available Test Tools

- **pytest** (>=7.0) - Test framework
- **pytest-cov** (>=4.0) - Coverage reporting
- **pytest-mock** (>=3.10) - Mocking utilities
- **pytest-asyncio** (>=0.21) - Async test support

## Configuration

Pytest is configured in `pyproject.toml` under `[tool.pytest.ini_options]`.

Common options:
- `testpaths` - Directories to search for tests
- `python_files` - Patterns for test files (test_*.py, *_test.py)
- `addopts` - Default command-line options
