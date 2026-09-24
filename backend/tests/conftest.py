"""Pytest fixtures and configuration for NEXUS backend test suite."""

import os
import sys
import pytest
from fastapi.testclient import TestClient

# Ensure backend root is in python path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.config import Settings, get_settings
from app.main import create_application


def get_test_settings() -> Settings:
    """Provide isolated settings for the test runner."""
    return Settings(
        APP_ENV="test",
        DEBUG=False,
        DATABASE_URL="sqlite:///:memory:",
        BACKEND_CORS_ORIGINS=["http://localhost:3000"],
    )



@pytest.fixture(scope="session")
def test_app():
    """Create and return a configured FastAPI test application."""
    app = create_application()
    app.dependency_overrides[get_settings] = get_test_settings
    return app


@pytest.fixture(scope="session")
def client(test_app) -> TestClient:
    """Provide a TestClient instance bound to the test application."""
    with TestClient(test_app) as test_client:
        yield test_client
