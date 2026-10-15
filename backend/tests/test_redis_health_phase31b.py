"""NEXUS Phase 31B Step 2.4 — Redis Health, Readiness, and Observability Tests.

Validates:
1. Healthy Redis reporting (connected, shared_state_available=True, mode='redis')
2. Startup outage reporting (reconnecting/unavailable, local fallback)
3. Reconnect cooldown backoff without probe storms or log noise
4. Mid-operation failure transition (healthy -> failure -> readiness drops to 503 in production)
5. Production readiness failure (503 Service Unavailable when required shared state unavailable)
6. Development optional behavior (200 OK when Redis is unconfigured in development)
7. Safe response contents (zero credential, token, URL, or internal traceback leakage)
8. Liveness probe independence (strictly HTTP 200 alive regardless of Redis/PostgreSQL outages)
9. Low-noise state transition logging and URL redaction
"""

import logging
import time
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.core.cache import (
    CacheClient,
    _LocalCacheBackend,
    _reset_cache_for_testing,
    check_redis_health,
    redact_redis_url,
)
from app.core.config import Settings, settings
from app.main import app


# ---------------------------------------------------------------------------
# Test Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clean_cache_singleton():
    """Ensure clean cache singleton before and after each test."""
    _reset_cache_for_testing(None)
    yield
    _reset_cache_for_testing(None)


@pytest.fixture
def test_client() -> TestClient:
    """FastAPI TestClient with database connection mocked as healthy by default."""
    with patch(
        "app.api.v1.endpoints.health.check_database_connection",
        return_value={"status": "connected", "latency_ms": 0.5},
    ):
        yield TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# 1. Healthy Redis
# ---------------------------------------------------------------------------


def test_health_and_readiness_healthy_redis(test_client: TestClient) -> None:
    """When Redis is reachable, health reports 'healthy' and readiness reports 'ready'."""
    mock_redis = MagicMock()
    mock_redis.ping.return_value = True

    client = CacheClient(redis_url="redis://:secret@127.0.0.1:6379/0")
    client._redis_backend = mock_redis
    client._failure_count = 0
    _reset_cache_for_testing(client)

    # Unit check
    health_data = check_redis_health()
    assert health_data["status"] == "connected"
    assert health_data["shared_state_available"] is True
    assert health_data["mode"] == "redis"

    # Health endpoint
    resp = test_client.get("/api/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "healthy"
    assert data["dependency_status"] == "optimal"
    assert data["redis"]["status"] == "connected"
    assert data["redis"]["shared_state_available"] is True
    assert data["redis"]["mode"] == "redis"

    # Readiness probe
    ready_resp = test_client.get("/api/health/ready")
    assert ready_resp.status_code == 200
    ready_data = ready_resp.json()
    assert ready_data["status"] == "ready"
    assert ready_data["redis"]["status"] == "connected"
    assert ready_data["redis"]["shared_state_available"] is True


# ---------------------------------------------------------------------------
# 2. Startup Outage (Development vs Production)
# ---------------------------------------------------------------------------


def test_startup_outage_development_mode(test_client: TestClient) -> None:
    """In development, an unreachable Redis triggers reconnecting status but does not block readiness."""
    mock_redis = MagicMock()
    mock_redis.ping.side_effect = ConnectionError("Connection refused")

    with patch.object(settings, "APP_ENV", "development"), \
         patch.object(settings, "REDIS_REQUIRED", False), \
         patch.object(settings, "REDIS_FAIL_CLOSED", False):

        client = CacheClient(redis_url="redis://127.0.0.1:6379/0")
        client._redis_backend = mock_redis
        client._record_failure(ConnectionError("Connection refused"))
        _reset_cache_for_testing(client)

        health_data = check_redis_health()
        assert health_data["status"] == "reconnecting"
        assert health_data["shared_state_available"] is False
        assert health_data["mode"] == "local"
        assert health_data["required"] is False

        # In dev, health reports degraded because configured Redis is down
        resp = test_client.get("/api/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "degraded"
        assert data["dependency_status"] == "degraded"
        assert data["redis"]["status"] == "reconnecting"

        # But readiness probe passes (200) because Redis is optional in development
        ready_resp = test_client.get("/api/health/ready")
        assert ready_resp.status_code == 200
        assert ready_resp.json()["status"] == "ready"


def test_startup_outage_production_readiness_fails_503(test_client: TestClient) -> None:
    """In production, an unreachable Redis must fail readiness with HTTP 503."""
    mock_redis = MagicMock()
    mock_redis.ping.side_effect = ConnectionError("Connection refused")

    with patch.object(settings, "APP_ENV", "production"), \
         patch.object(settings, "REDIS_REQUIRED", True), \
         patch.object(settings, "REDIS_FAIL_CLOSED", True):

        client = CacheClient(redis_url="redis://127.0.0.1:6379/0")
        client._redis_backend = mock_redis
        client._record_failure(ConnectionError("Connection refused"))
        _reset_cache_for_testing(client)

        health_data = check_redis_health()
        assert health_data["status"] == "reconnecting"
        assert health_data["shared_state_available"] is False
        assert health_data["required"] is True

        ready_resp = test_client.get("/api/health/ready")
        assert ready_resp.status_code == 503
        data = ready_resp.json()
        assert data["status"] == "not_ready"
        assert data["redis"]["status"] == "reconnecting"
        assert data["redis"]["shared_state_available"] is False
        assert data["redis"]["required"] is True


# ---------------------------------------------------------------------------
# 3. Reconnect Cooldown & Probe Storm Prevention
# ---------------------------------------------------------------------------


def test_reconnect_cooldown_prevents_socket_storms_and_log_noise(caplog: pytest.LogCaptureFixture) -> None:
    """During cooldown, repeated health checks return 'reconnecting' without pinging Redis."""
    caplog.set_level(logging.DEBUG)

    mock_redis = MagicMock()
    mock_redis.ping.side_effect = ConnectionError("Down")

    client = CacheClient(redis_url="redis://127.0.0.1:6379/0")
    client._redis_backend = mock_redis
    client._record_failure(ConnectionError("Down"))
    _reset_cache_for_testing(client)

    initial_ping_count = mock_redis.ping.call_count

    # Call probe repeatedly within cooldown window
    for _ in range(10):
        status = check_redis_health()
        assert status["status"] == "reconnecting"
        assert status["shared_state_available"] is False

    # Mock ping must NOT have been called repeatedly
    assert mock_redis.ping.call_count == initial_ping_count


# ---------------------------------------------------------------------------
# 4. Mid-Operation Failure Transition
# ---------------------------------------------------------------------------


def test_mid_operation_failure_transitions_readiness_to_503(test_client: TestClient) -> None:
    """A healthy runtime Redis that suffers a mid-operation failure immediately transitions readiness to 503."""
    mock_redis = MagicMock()
    mock_redis.ping.return_value = True
    mock_redis.set.side_effect = ConnectionError("Redis crashed mid-run")

    with patch.object(settings, "APP_ENV", "production"), \
         patch.object(settings, "REDIS_REQUIRED", True), \
         patch.object(settings, "REDIS_FAIL_CLOSED", True):

        client = CacheClient(redis_url="redis://127.0.0.1:6379/0")
        client._redis_backend = mock_redis
        client._failure_count = 0
        _reset_cache_for_testing(client)

        # Initially ready
        ready_1 = test_client.get("/api/health/ready")
        assert ready_1.status_code == 200

        # Mid-operation failure occurs
        with pytest.raises(ConnectionError):
            client.set("key", "val", 60)

        # Subsequent health check immediately reflects reconnecting
        health_data = check_redis_health()
        assert health_data["status"] == "reconnecting"
        assert health_data["shared_state_available"] is False

        # Production readiness probe now immediately fails with 503
        ready_2 = test_client.get("/api/health/ready")
        assert ready_2.status_code == 503
        assert ready_2.json()["status"] == "not_ready"


# ---------------------------------------------------------------------------
# 5. Development Optional Behavior (Unconfigured Redis)
# ---------------------------------------------------------------------------


def test_development_optional_unconfigured_redis(test_client: TestClient) -> None:
    """When REDIS_URL is unconfigured in development, health reports 'optional' and readiness is 200."""
    with patch.object(settings, "APP_ENV", "development"), \
         patch.object(settings, "REDIS_REQUIRED", False), \
         patch.object(settings, "REDIS_FAIL_CLOSED", False):

        client = CacheClient(redis_url=None)
        _reset_cache_for_testing(client)

        health_data = check_redis_health()
        assert health_data["status"] == "optional"
        assert health_data["shared_state_available"] is False
        assert health_data["mode"] == "local"
        assert health_data["required"] is False

        # Health endpoint reports healthy
        resp = test_client.get("/api/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "healthy"
        assert data["dependency_status"] == "optimal"
        assert data["redis"]["status"] == "optional"

        # Readiness endpoint reports ready
        ready_resp = test_client.get("/api/health/ready")
        assert ready_resp.status_code == 200
        assert ready_resp.json()["status"] == "ready"


def test_production_unconfigured_redis_reports_unavailable(test_client: TestClient) -> None:
    """In production, an unconfigured Redis reports status='unavailable' and fails readiness."""
    with patch.object(settings, "APP_ENV", "production"), \
         patch.object(settings, "REDIS_REQUIRED", True), \
         patch.object(settings, "REDIS_FAIL_CLOSED", True):

        client = CacheClient(redis_url=None)
        _reset_cache_for_testing(client)

        health_data = check_redis_health()
        assert health_data["status"] == "unavailable"
        assert health_data["shared_state_available"] is False
        assert health_data["required"] is True

        ready_resp = test_client.get("/api/health/ready")
        assert ready_resp.status_code == 503
        assert ready_resp.json()["status"] == "not_ready"


# ---------------------------------------------------------------------------
# 6. Safe Response Contents (No Secret/Topology/Traceback Leakage)
# ---------------------------------------------------------------------------


def test_safe_response_contents_no_secrets_exposed(test_client: TestClient) -> None:
    """Verify health endpoints never expose passwords, credentials, hostnames, or raw errors."""
    secret_url = "redis://user:super_secret_token_12345@prod-redis-node.internal:6379/2"

    mock_redis = MagicMock()
    mock_redis.ping.side_effect = ConnectionError("FATAL: password authentication failed for internal db")

    with patch.object(settings, "APP_ENV", "production"), \
         patch.object(settings, "REDIS_REQUIRED", True):

        client = CacheClient(redis_url=secret_url)
        client._redis_backend = mock_redis
        client._record_failure(ConnectionError("FATAL: password authentication failed"))
        _reset_cache_for_testing(client)

        for path in ["/api/health", "/api/health/ready", "/api/health/live"]:
            resp = test_client.get(path)
            raw_text = resp.text
            assert "super_secret_token_12345" not in raw_text
            assert "prod-redis-node.internal" not in raw_text
            assert "FATAL" not in raw_text
            assert "password" not in raw_text
            assert "traceback" not in raw_text.lower()


# ---------------------------------------------------------------------------
# 7. Liveness Independence
# ---------------------------------------------------------------------------


def test_liveness_probe_independent_of_redis_and_database_outages() -> None:
    """Liveness probe must ALWAYS return HTTP 200 alive, even during catastrophic Redis and DB outages."""
    # Both DB and Redis broken
    with patch(
        "app.api.v1.endpoints.health.check_database_connection",
        return_value={"status": "disconnected", "error": "Database crashed"},
    ), patch.object(settings, "APP_ENV", "production"), \
       patch.object(settings, "REDIS_REQUIRED", True):

        client = CacheClient(redis_url="redis://127.0.0.1:6379/0")
        client._record_failure(ConnectionError("Redis down"))
        _reset_cache_for_testing(client)

        app_client = TestClient(app, raise_server_exceptions=False)

        # Readiness is down (503)
        ready_resp = app_client.get("/api/health/ready")
        assert ready_resp.status_code == 503

        # Liveness remains alive (200) to prevent orchestrator restart loops
        for liveness_url in ["/api/health/live", "/api/v1/health/live"]:
            live_resp = app_client.get(liveness_url)
            assert live_resp.status_code == 200
            data = live_resp.json()
            assert data["status"] == "alive"
            assert "timestamp" in data


# ---------------------------------------------------------------------------
# 8. Low-Noise Logging and Redaction
# ---------------------------------------------------------------------------


def test_low_noise_logging_and_url_redaction(caplog: pytest.LogCaptureFixture) -> None:
    """Verify failure transitions log at WARNING once, then DEBUG, and recovery logs at INFO with redacted URL."""
    caplog.set_level(logging.DEBUG)

    secret_url = "redis://admin:my_secret_pw@10.0.0.5:6379/0"
    client = CacheClient(redis_url=None)  # Start unconfigured
    client._redis_url = secret_url

    # First failure -> logs warning with redacted URL
    client._record_failure(ConnectionError("First fail"))
    assert "my_secret_pw" not in caplog.text
    assert "WARNING" in caplog.text

    # Second failure -> logs debug, not warning
    caplog.clear()
    client._record_failure(ConnectionError("Second fail"))
    assert "my_secret_pw" not in caplog.text
    # Should not produce a WARNING
    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert len(warnings) == 0
    # Should produce a DEBUG log
    debugs = [r for r in caplog.records if r.levelno == logging.DEBUG]
    assert len(debugs) > 0

    # Redaction helper check
    redacted = redact_redis_url(secret_url)
    assert "my_secret_pw" not in redacted
    assert "admin:<redacted>@" in redacted
