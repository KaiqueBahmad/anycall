# Testing Guide for AnyCall Python Library

## Setup

Install development dependencies:

```bash
cd implementations/python
uv sync
```

## Running Tests

Run these from `implementations/python/lib`.

### Run all tests
```bash
uv run pytest
```

### Run with coverage report
```bash
uv run pytest --cov=anycall --cov-report=html
```

### Run a single test class or test
```bash
uv run pytest src/anycall/test_client.py::TestWaiterDrivenReaping
uv run pytest -k max_queue_depth
```

## Test Structure

Tests live next to the code in `src/anycall/test_*.py`. They run against an
in-memory fake of the Redis adapter, so no Redis server is needed.

## Available Test Tools

- **pytest** (>=7.0) - Test framework
- **pytest-cov** (>=4.0) - Coverage reporting

## Configuration

Pytest is configured in `pyproject.toml` under `[tool.pytest.ini_options]`.
