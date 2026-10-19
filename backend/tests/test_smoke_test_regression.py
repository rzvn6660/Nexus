"""Regression tests for scripts/smoke_test.py.

Validates:
1. Consistent resolution of configured database URLs (DATABASE_URL / TEST_DATABASE_URL).
2. Live/CI environment detection flags.
3. Strict failure on degraded database status when require_healthy is set or in CI.
4. Preserved development fallback allowing degraded status when offline/dev mode.
"""

import os
from unittest.mock import MagicMock, patch
import pytest

import scripts.smoke_test as smoke_test


def test_resolve_configured_database_url_precedence():
    """Verify TEST_DATABASE_URL takes precedence over DATABASE_URL."""
    with patch.dict(os.environ, {}, clear=True):
        assert smoke_test.resolve_configured_database_url() is None

    with patch.dict(os.environ, {"DATABASE_URL": "postgresql://main_user:pass@localhost:5432/main_db"}, clear=True):
        assert smoke_test.resolve_configured_database_url() == "postgresql://main_user:pass@localhost:5432/main_db"

    with patch.dict(
        os.environ,
        {
            "DATABASE_URL": "postgresql://main_user:pass@localhost:5432/main_db",
            "TEST_DATABASE_URL": "postgresql://test_user:pass@localhost:5439/test_db",
        },
        clear=True,
    ):
        assert smoke_test.resolve_configured_database_url() == "postgresql://test_user:pass@localhost:5439/test_db"


@pytest.mark.parametrize(
    "env_vars,expected",
    [
        ({}, False),
        ({"CI": "true"}, True),
        ({"CI": "1"}, True),
        ({"REQUIRE_POSTGRES": "true"}, True),
        ({"REQUIRE_POSTGRES": "1"}, True),
        ({"APP_ENV": "production"}, True),
        ({"APP_ENV": "prod"}, True),
        ({"APP_ENV": "staging"}, True),
        ({"APP_ENV": "development"}, False),
    ],
)
def test_is_live_or_ci_environment(env_vars, expected):
    """Verify live/CI environment detection strictly identifies mandatory environments."""
    with patch.dict(os.environ, env_vars, clear=True):
        assert smoke_test.is_live_or_ci_environment() is expected


def _build_mock_client(health_status: str, db_status: str):
    """Construct mock client responding to smoke test endpoints."""
    mock_client = MagicMock()

    def _get(url, **kwargs):
        resp = MagicMock()
        if url == "/":
            resp.status_code = 200
            resp.json.return_value = {
                "name": "NEXUS",
                "title": "NEXUS - Agentic Business Intelligence Platform",
                "health": "/api/v1/health",
                "readiness": "/api/v1/health/ready",
            }
        elif url == "/api/v1/health/live":
            resp.status_code = 200
            resp.json.return_value = {"status": "alive"}
            resp.headers = {"X-Request-ID": kwargs.get("headers", {}).get("X-Request-ID", "req-1"), "X-Process-Time-Ms": "1.2"}
        elif url == "/api/v1/health":
            resp.status_code = 200
            resp.json.return_value = {
                "status": health_status,
                "database": {"status": db_status},
            }
        elif url == "/api/v1/data/health":
            resp.status_code = 200
            resp.json.return_value = {"layer": "data_layer", "registered_models": 6}
        elif url == "/api/v1/analytics/summary":
            resp.status_code = 200
            resp.json.return_value = {
                "success": True,
                "data": {"net_sales": 100.0, "orders": 5, "average_order_value": 20.0, "gross_profit": 50.0},
                "evidence": {"source": "db"},
            }
        else:
            resp.status_code = 404
        return resp

    def _post(url, **kwargs):
        resp = MagicMock()
        if url == "/api/v1/semantic/resolve":
            query = kwargs.get("json", {}).get("query", "")
            resp.status_code = 200
            if "turnover" in query:
                resp.json.return_value = {"canonical_name": "net_revenue", "is_ambiguous": True}
            else:
                resp.json.return_value = {"canonical_name": "net_revenue", "is_ambiguous": False}
        elif url == "/api/v1/knowledge/search":
            resp.status_code = 200
            resp.json.return_value = {"chunks": [{"text": "policy"}]}
        elif url == "/api/v1/forecast/analyze":
            query = kwargs.get("json", {}).get("query", "")
            if "48 months" in query:
                resp.status_code = 422
            else:
                resp.status_code = 200
                resp.json.return_value = {"target_metric": "revenue", "predictions": [1, 2, 3]}
        elif url == "/api/v1/investigation/analyze":
            resp.status_code = 200
            resp.json.return_value = {"summary": "declined", "hypotheses": ["h1"], "status": "completed"}
        elif url == "/api/v1/agent/analyze":
            resp.status_code = 200
            resp.json.return_value = {"status": "completed", "evidence": {}}
        elif url == "/api/v1/data/ingest/csv":
            resp.status_code = 400
        else:
            resp.status_code = 404
        return resp

    mock_client.get = _get
    mock_client.post = _post
    return mock_client


def test_smoke_test_fails_on_degraded_in_ci():
    """Verify smoke test fails with AssertionError when health is degraded in CI mode."""
    mock_client = _build_mock_client(health_status="degraded", db_status="disconnected")
    with patch.dict(os.environ, {"CI": "true"}, clear=True):
        with pytest.raises(AssertionError, match="Release gate status must be 'healthy' in CI/production"):
            smoke_test.run_smoke_test(lambda: mock_client)


def test_smoke_test_fails_on_degraded_when_require_healthy_flag():
    """Verify smoke test fails with AssertionError when require_healthy is explicitly passed."""
    mock_client = _build_mock_client(health_status="degraded", db_status="disconnected")
    with patch.dict(os.environ, {}, clear=True):
        with pytest.raises(AssertionError, match="Release gate status must be 'healthy' in CI/production"):
            smoke_test.run_smoke_test(lambda: mock_client, require_healthy=True)


def test_smoke_test_allows_degraded_in_development_fallback():
    """Verify smoke test allows degraded status when running in local development mode without CI flags."""
    mock_client = _build_mock_client(health_status="degraded", db_status="disconnected")
    with patch.dict(os.environ, {}, clear=True):
        # Should not raise
        smoke_test.run_smoke_test(lambda: mock_client, require_healthy=False)


def test_smoke_test_passes_when_healthy_in_ci():
    """Verify smoke test completes all steps when healthy under strict CI mode."""
    mock_client = _build_mock_client(health_status="healthy", db_status="connected")
    with patch.dict(os.environ, {"CI": "true", "REQUIRE_POSTGRES": "true"}, clear=True):
        smoke_test.run_smoke_test(lambda: mock_client, require_healthy=True)
