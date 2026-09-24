"""Tests for configuration parsing and database connectivity check behavior."""

from sqlalchemy import create_engine
from app.core.config import Settings
from app.core.database import check_database_connection


def test_settings_defaults() -> None:
    """Validate default configuration settings."""
    cfg = Settings()
    assert cfg.APP_NAME == "NEXUS"
    assert "postgresql" in cfg.DATABASE_URL
    assert cfg.API_V1_PREFIX == "/api/v1"
    assert isinstance(cfg.BACKEND_CORS_ORIGINS, list)
    assert not cfg.is_production


def test_cors_origins_parsing() -> None:
    """Validate CORS string parsing into string list."""
    cfg = Settings(BACKEND_CORS_ORIGINS="http://example.com, https://nexus.ai")
    assert cfg.BACKEND_CORS_ORIGINS == ["http://example.com", "https://nexus.ai"]


def test_check_database_connection_connected() -> None:
    """Validate database connectivity check with an active in-memory SQLite engine."""
    sqlite_engine = create_engine("sqlite:///:memory:")
    res = check_database_connection(target_engine=sqlite_engine)
    assert res["status"] == "connected"
    assert "latency_ms" in res
    assert res["latency_ms"] >= 0.0


def test_check_database_connection_disconnected_graceful() -> None:
    """
    Validate that check_database_connection handles unreachable DB gracefully
    without raising an unhandled exception.
    """
    unreachable_engine = create_engine(
        "postgresql+psycopg://nexus_user:fake_password@127.0.0.1:59999/nonexistent",
        connect_args={"connect_timeout": 1},
    )
    res = check_database_connection(target_engine=unreachable_engine)
    assert isinstance(res, dict)
    assert res["status"] == "disconnected"
    assert "error" in res
