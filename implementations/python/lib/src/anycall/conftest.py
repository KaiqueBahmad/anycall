"""Pytest configuration and shared fixtures for AnyCall tests."""

import pytest


@pytest.fixture
def anyCall_config():
    """Fixture for AnyCall test configuration."""
    class Config:
        redis_uri = "redis://localhost:16379"
        timeout_ms = 5000
        metrics_enabled = False
    return Config


@pytest.fixture(autouse=True)
def reset_environment():
    """Reset environment before/after each test."""
    yield
    # Cleanup after test if needed
    pass
