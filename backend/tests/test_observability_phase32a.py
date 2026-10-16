"""Targeted tests for Phase 32A Observability and Security Headers.

Verifies:
1. Sentry error tracking: safe disabled mode, initialization with DSN, graceful failure handling,
   and rigorous scrubbing of passwords, tokens, auth headers, and request bodies.
2. Prometheus operational metrics: exporter endpoint, token-based authentication gating,
   disabled mode, low-cardinality path normalization, and request counter increments.
3. Security headers: OWASP baseline headers, Content-Security-Policy (report-only and enforcing),
   Permissions-Policy, and conditional HTTP Strict Transport Security (HSTS).
"""

from unittest.mock import MagicMock, patch
import pytest
from pydantic import ValidationError
from fastapi.testclient import TestClient

from app.core.config import Settings, settings
from app.core.metrics import (
    get_latest_metrics,
    get_route_handler,
    get_status_class,
    normalize_path,
)
from app.core.sentry import (
    before_breadcrumb_handler,
    before_send_handler,
    init_sentry,
    scrub_query_string,
    scrub_sensitive_dict,
)
from app.main import create_application


@pytest.fixture
def obs_client():
    """Create isolated FastAPI test client with managed lifespan context."""
    app = create_application()
    with TestClient(app) as test_client:
        yield test_client


# ==============================================================================
# 1. SENTRY ERROR TRACKING & SANITIZATION TESTS
# ==============================================================================

def test_sentry_disabled_by_default():
    """When SENTRY_DSN is None or empty, initialization safely returns False."""
    with patch.object(settings, "SENTRY_DSN", None):
        result = init_sentry(process_name="api")
        assert result is False

    with patch.object(settings, "SENTRY_DSN", "   "):
        result = init_sentry(process_name="scheduler")
        assert result is False


def test_sentry_init_with_valid_dsn():
    """When SENTRY_DSN is configured, sentry_sdk.init is called with safe settings."""
    with patch("sentry_sdk.init") as mock_init, patch("sentry_sdk.set_tag") as mock_set_tag:
        with patch.object(settings, "SENTRY_DSN", "https://key@sentry.io/123456"):
            with patch.object(settings, "SENTRY_ENVIRONMENT", "production"):
                with patch.object(settings, "SENTRY_TRACES_SAMPLE_RATE", 0.25):
                    result = init_sentry(process_name="api")
                    assert result is True
                    mock_init.assert_called_once()
                    kwargs = mock_init.call_args.kwargs
                    assert kwargs["dsn"] == "https://key@sentry.io/123456"
                    assert kwargs["environment"] == "production"
                    assert kwargs["send_default_pii"] is False
                    assert kwargs["request_bodies"] == "never"
                    assert kwargs["traces_sample_rate"] == 0.25
                    mock_set_tag.assert_any_call("process", "api")


def test_sentry_init_handles_exception_safely():
    """If sentry_sdk.init raises an exception, init_sentry handles it without crashing."""
    with patch("sentry_sdk.init", side_effect=RuntimeError("Invalid DSN format")):
        with patch.object(settings, "SENTRY_DSN", "https://invalid-dsn"):
            result = init_sentry(process_name="scheduler")
            assert result is False  # Safe failure: does not raise


def test_sentry_scrub_sensitive_dict():
    """Recursive dictionary scrubber redacts sensitive keys and auth headers."""
    payload = {
        "user_id": "usr-123",
        "username": "jdoe",
        "password": "super-secret-password",
        "api_key": "nexus-key-xyz",
        "auth_token": "jwt-token-val",
        "nested": {
            "secret_value": "hide-me",
            "safe_value": 42,
            "session_id": "sess-999",
            "deep": [
                {"credential_hash": "hash-abc", "item_name": "Widget A"},
                "plain_string",
            ],
        },
    }

    scrubbed = scrub_sensitive_dict(payload)
    assert scrubbed["user_id"] == "usr-123"
    assert scrubbed["username"] == "jdoe"
    assert scrubbed["password"] == "[REDACTED]"
    assert scrubbed["api_key"] == "[REDACTED]"
    assert scrubbed["auth_token"] == "[REDACTED]"
    assert scrubbed["nested"]["secret_value"] == "[REDACTED]"
    assert scrubbed["nested"]["safe_value"] == 42
    assert scrubbed["nested"]["session_id"] == "[REDACTED]"
    assert scrubbed["nested"]["deep"][0]["credential_hash"] == "[REDACTED]"
    assert scrubbed["nested"]["deep"][0]["item_name"] == "Widget A"
    assert scrubbed["nested"]["deep"][1] == "plain_string"


def test_sentry_scrub_query_string():
    """Query parameter scrubber redacts sensitive query values while keeping keys."""
    raw_query = "page=1&limit=50&token=sensitive123&api_key=secret999&filter=active"
    scrubbed = scrub_query_string(raw_query)
    assert "page=1" in scrubbed
    assert "limit=50" in scrubbed
    assert "filter=active" in scrubbed
    assert "token=%5BREDACTED%5D" in scrubbed or "token=[REDACTED]" in scrubbed
    assert "api_key=%5BREDACTED%5D" in scrubbed or "api_key=[REDACTED]" in scrubbed
    assert "sensitive123" not in scrubbed
    assert "secret999" not in scrubbed


def test_sentry_before_send_handler_redacts_event():
    """before_send_handler scrubs request headers, cookies, request bodies, user PII, and breadcrumbs."""
    event = {
        "request": {
            "url": "https://api.nexus.internal/api/v1/auth/login",
            "headers": {
                "Authorization": "Bearer sensitive-jwt-token",
                "X-API-Key": "secret-prototype-key",
                "User-Agent": "Mozilla/5.0",
                "Content-Type": "application/json",
            },
            "cookies": {"session": "sess-cookie-123"},
            "query_string": "token=query-token&page=2",
            "data": {"password": "raw-password-attempt", "email": "test@nexus.internal"},
        },
        "user": {
            "id": "12345",
            "email": "sensitive@nexus.internal",
            "username": "admin_user",
            "ip_address": "192.168.1.100",
        },
        "extra": {
            "secret_internal_key": "confidential",
            "public_metric": 100,
        },
        "breadcrumbs": {
            "values": [
                {
                    "category": "http",
                    "data": {"auth_token": "bc-token", "status": 200},
                }
            ]
        },
    }

    scrubbed_event = before_send_handler(event, {})
    assert scrubbed_event is not None

    req = scrubbed_event["request"]
    assert req["headers"]["Authorization"] == "[REDACTED]"
    assert req["headers"]["X-API-Key"] == "[REDACTED]"
    assert req["headers"]["User-Agent"] == "Mozilla/5.0"
    assert req["cookies"] == "[REDACTED_COOKIES]"
    assert req["data"] == "[REDACTED_REQUEST_BODY]"
    assert "query-token" not in req["query_string"]

    usr = scrubbed_event["user"]
    assert "email" not in usr
    assert "username" not in usr
    assert "ip_address" not in usr
    assert usr.get("id") == "12345"

    assert scrubbed_event["extra"]["secret_internal_key"] == "[REDACTED]"
    assert scrubbed_event["extra"]["public_metric"] == 100

    crumb = scrubbed_event["breadcrumbs"]["values"][0]
    assert crumb["data"]["auth_token"] == "[REDACTED]"
    assert crumb["data"]["status"] == 200


def test_sentry_before_breadcrumb_handler():
    """Breadcrumb handler scrubs sensitive keys from breadcrumb data."""
    crumb = {
        "category": "auth",
        "data": {"password_attempt": "123456", "endpoint": "/api/v1/auth/login"},
    }
    result = before_breadcrumb_handler(crumb, {})
    assert result["data"]["password_attempt"] == "[REDACTED]"
    assert result["data"]["endpoint"] == "/api/v1/auth/login"


# ==============================================================================
# 2. PROMETHEUS OPERATIONAL METRICS TESTS
# ==============================================================================

def test_metrics_endpoint_accessible(obs_client):
    """GET /api/v1/metrics and /api/metrics return 200 with Prometheus text format."""
    with patch.object(settings, "METRICS_AUTH_TOKEN", None):
        response_v1 = obs_client.get("/api/v1/metrics")
        assert response_v1.status_code == 200
        assert "text/plain" in response_v1.headers["content-type"]
        assert "nexus_http_requests_total" in response_v1.text

        response_root = obs_client.get("/api/metrics")
        assert response_root.status_code == 200
        assert "nexus_http_requests_total" in response_root.text


def test_metrics_disabled_returns_404(obs_client):
    """When METRICS_ENABLED is False, metrics endpoint returns 404 Not Found."""
    with patch.object(settings, "METRICS_ENABLED", False):
        response = obs_client.get("/api/v1/metrics")
        assert response.status_code == 404
        assert "disabled" in response.json()["detail"].lower()


def test_metrics_auth_token_gating(obs_client):
    """When METRICS_AUTH_TOKEN is configured, unauthorized requests return 401."""
    test_token = "scraper-super-secret-token-321"
    with patch.object(settings, "METRICS_AUTH_TOKEN", test_token):
        # 1. No token provided
        unauth_resp = obs_client.get("/api/v1/metrics")
        assert unauth_resp.status_code == 401

        # 2. Invalid token provided
        bad_token_resp = obs_client.get(
            "/api/v1/metrics",
            headers={"Authorization": "Bearer wrong-token"},
        )
        assert bad_token_resp.status_code == 401

        # 3. Valid Bearer token
        valid_bearer_resp = obs_client.get(
            "/api/v1/metrics",
            headers={"Authorization": f"Bearer {test_token}"},
        )
        assert valid_bearer_resp.status_code == 200
        assert "nexus_http_requests_total" in valid_bearer_resp.text

        # 4. Valid X-Metrics-Token header
        valid_header_resp = obs_client.get(
            "/api/v1/metrics",
            headers={"X-Metrics-Token": test_token},
        )
        assert valid_header_resp.status_code == 200
        assert "nexus_http_requests_total" in valid_header_resp.text


# ==============================================================================
# 2B. PRODUCTION METRICS SECURITY & FAIL-CLOSED REGRESSION TESTS
# ==============================================================================

VALID_PROD_SECRET = "c8f2a1b9e4d7301648a5c2f901b8e4d7c8f2a1b9e4d7301648a5c2f901b8e4d7"
VALID_PROD_JWT = "9b4f1a2c3d5e789012345678abcdef019b4f1a2c3d5e789012345678abcdef01"
VALID_METRICS_TOKEN = "c8f2a1b9e4d7301648a5c2f901b8e4d7"


def test_production_metrics_enabled_without_token_rejected_at_startup(monkeypatch):
    """When APP_ENV=production and METRICS_ENABLED=True, missing METRICS_AUTH_TOKEN fails startup."""
    monkeypatch.delenv("METRICS_AUTH_TOKEN", raising=False)
    with pytest.raises(ValidationError) as exc_info:
        Settings(
            APP_ENV="production",
            METRICS_ENABLED=True,
            METRICS_AUTH_TOKEN=None,
            SECRET_KEY=VALID_PROD_SECRET,
            AUTH_JWT_SECRET=VALID_PROD_JWT,
        )
    err = str(exc_info.value)
    assert "METRICS_AUTH_TOKEN is mandatory when METRICS_ENABLED=True in production" in err


def test_production_metrics_enabled_with_blank_token_rejected_at_startup():
    """When APP_ENV=production, empty or whitespace-only METRICS_AUTH_TOKEN fails startup."""
    for blank in ["", "   ", "\t\n  "]:
        with pytest.raises(ValidationError) as exc_info:
            Settings(
                APP_ENV="production",
                METRICS_ENABLED=True,
                METRICS_AUTH_TOKEN=blank,
                SECRET_KEY=VALID_PROD_SECRET,
                AUTH_JWT_SECRET=VALID_PROD_JWT,
            )
        err = str(exc_info.value)
        assert "METRICS_AUTH_TOKEN is mandatory when METRICS_ENABLED=True in production" in err


def test_production_metrics_insecure_placeholder_rejected_at_startup():
    """Insecure placeholder tokens are rejected in production."""
    for placeholder in [
        "change-me-long-enough-32-chars-token",
        "change-in-production-token-1234567",
        "your-metrics-token-is-here-secure",
        "example-scraper-token-with-length",
        "password-token-longer-than-16-chars",
        "my-secret-key-that-is-long-enough",
    ]:
        with pytest.raises(ValidationError) as exc_info:
            Settings(
                APP_ENV="production",
                METRICS_ENABLED=True,
                METRICS_AUTH_TOKEN=placeholder,
                SECRET_KEY=VALID_PROD_SECRET,
                AUTH_JWT_SECRET=VALID_PROD_JWT,
            )
        err = str(exc_info.value)
        assert "insecure placeholder token" in err


def test_production_metrics_short_token_rejected_at_startup():
    """Tokens shorter than 16 characters fail startup in production."""
    with pytest.raises(ValidationError) as exc_info:
        Settings(
            APP_ENV="production",
            METRICS_ENABLED=True,
            METRICS_AUTH_TOKEN="short-abc-123",
            SECRET_KEY=VALID_PROD_SECRET,
            AUTH_JWT_SECRET=VALID_PROD_JWT,
        )
    err = str(exc_info.value)
    assert "mandatory production minimum of 16 characters" in err


def test_production_metrics_valid_token_permits_startup():
    """Cryptographically strong token >= 16 chars succeeds in production."""
    cfg = Settings(
        APP_ENV="production",
        METRICS_ENABLED=True,
        METRICS_AUTH_TOKEN=VALID_METRICS_TOKEN,
        SECRET_KEY=VALID_PROD_SECRET,
        AUTH_JWT_SECRET=VALID_PROD_JWT,
    )
    assert cfg.is_production is True
    assert cfg.METRICS_AUTH_TOKEN == VALID_METRICS_TOKEN


def test_production_metrics_disabled_allows_startup_without_token():
    """When METRICS_ENABLED=False in production, METRICS_AUTH_TOKEN is not required."""
    cfg = Settings(
        APP_ENV="production",
        METRICS_ENABLED=False,
        METRICS_AUTH_TOKEN=None,
        SECRET_KEY=VALID_PROD_SECRET,
        AUTH_JWT_SECRET=VALID_PROD_JWT,
    )
    assert cfg.is_production is True
    assert cfg.METRICS_ENABLED is False


def test_production_endpoint_fails_closed_when_token_unconfigured(obs_client):
    """If configuration validation was somehow bypassed in production, endpoint fails closed (403)."""
    with patch.object(settings, "APP_ENV", "production"), patch.object(settings, "METRICS_AUTH_TOKEN", ""):
        # Anonymous access rejected
        resp_anon = obs_client.get("/api/v1/metrics")
        assert resp_anon.status_code == 403
        assert "forbidden in production when METRICS_AUTH_TOKEN is unconfigured" in resp_anon.json()["detail"]

        # Even with credential headers, access is forbidden
        resp_bearer = obs_client.get("/api/v1/metrics", headers={"Authorization": "Bearer some-token"})
        assert resp_bearer.status_code == 403

        resp_header = obs_client.get("/api/metrics", headers={"X-Metrics-Token": "some-token"})
        assert resp_header.status_code == 403


def test_production_endpoint_authorized_scraping_and_rejection_of_invalid(obs_client):
    """In production with a valid token: missing/bad credentials return 401; valid token returns 200."""
    with patch.object(settings, "APP_ENV", "production"), patch.object(settings, "METRICS_AUTH_TOKEN", VALID_METRICS_TOKEN):
        # Missing credentials -> 401
        resp_missing = obs_client.get("/api/v1/metrics")
        assert resp_missing.status_code == 401
        assert resp_missing.headers.get("WWW-Authenticate") == "Bearer"

        # Invalid Bearer token -> 401
        resp_bad_bearer = obs_client.get("/api/v1/metrics", headers={"Authorization": "Bearer wrong-token-123456789"})
        assert resp_bad_bearer.status_code == 401

        # Invalid X-Metrics-Token -> 401
        resp_bad_header = obs_client.get("/api/v1/metrics", headers={"X-Metrics-Token": "wrong-token-123456789"})
        assert resp_bad_header.status_code == 401

        # Valid Bearer token -> 200
        resp_ok_bearer = obs_client.get("/api/v1/metrics", headers={"Authorization": f"Bearer {VALID_METRICS_TOKEN}"})
        assert resp_ok_bearer.status_code == 200
        assert "nexus_http_requests_total" in resp_ok_bearer.text

        # Valid X-Metrics-Token -> 200 on /api/metrics alias
        resp_ok_header = obs_client.get("/api/metrics", headers={"X-Metrics-Token": VALID_METRICS_TOKEN})
        assert resp_ok_header.status_code == 200
        assert "nexus_http_requests_total" in resp_ok_header.text


def test_production_metrics_disabled_returns_404(obs_client):
    """When METRICS_ENABLED=False in production, endpoint returns 404 Not Found."""
    with patch.object(settings, "APP_ENV", "production"), patch.object(settings, "METRICS_ENABLED", False):
        resp = obs_client.get("/api/v1/metrics")
        assert resp.status_code == 404
        assert "disabled" in resp.json()["detail"].lower()


def test_development_test_behavior_remains_unauthenticated_intentional(obs_client):
    """In development/test (APP_ENV!=production), unauthenticated access is permitted when token unset."""
    with patch.object(settings, "APP_ENV", "test"), patch.object(settings, "METRICS_AUTH_TOKEN", None):
        resp = obs_client.get("/api/v1/metrics")
        assert resp.status_code == 200
        assert "nexus_http_requests_total" in resp.text

    with patch.object(settings, "APP_ENV", "development"), patch.object(settings, "METRICS_AUTH_TOKEN", ""):
        resp = obs_client.get("/api/metrics")
        assert resp.status_code == 200
        assert "nexus_http_requests_total" in resp.text


def test_metrics_auth_does_not_expose_secrets(obs_client, caplog):
    """Sensitive scraper tokens are never logged or exposed in error responses."""
    canary_token = "canary-super-secret-metrics-token-123456"
    with patch.object(settings, "APP_ENV", "production"), patch.object(settings, "METRICS_AUTH_TOKEN", canary_token):
        # Send bad token
        resp = obs_client.get("/api/v1/metrics", headers={"Authorization": "Bearer bad-canary-guess"})
        assert resp.status_code == 401
        assert canary_token not in resp.text
        assert canary_token not in str(resp.headers)
        assert canary_token not in caplog.text

        # Send empty
        resp2 = obs_client.get("/api/v1/metrics")
        assert resp2.status_code == 401
        assert canary_token not in resp2.text
        assert canary_token not in str(resp2.headers)
        assert canary_token not in caplog.text


def test_metrics_low_cardinality_path_normalization():
    """Path normalizer strips UUIDs, hashes, and numeric IDs to prevent label explosion."""
    # UUID path
    uuid_path = "/api/v1/businesses/123e4567-e89b-12d3-a456-426614174000/overview"
    assert normalize_path(uuid_path) == "/api/v1/businesses/:id/overview"

    # Numeric ID path
    num_path = "/api/v1/data/1024/download"
    assert normalize_path(num_path) == "/api/v1/data/:id/download"

    # Hex hash path
    hash_path = "/api/v1/tokens/abcdef0123456789abcdef0123456789/verify"
    assert normalize_path(hash_path) == "/api/v1/tokens/:hash/verify"

    # Normal static path preserved
    assert normalize_path("/api/health") == "/api/health"

    # Deep path bounded
    deep_path = "/a/b/c/d/e/f/g/h/i"
    normalized = normalize_path(deep_path)
    assert normalized.endswith("/:rest")


def test_metrics_status_class():
    """Status code classes are categorized into standard Prometheus labels."""
    assert get_status_class(200) == "2xx"
    assert get_status_class(204) == "2xx"
    assert get_status_class(301) == "3xx"
    assert get_status_class(400) == "4xx"
    assert get_status_class(404) == "4xx"
    assert get_status_class(500) == "5xx"
    assert get_status_class(503) == "5xx"
    assert get_status_class(999) == "unknown"


def test_metrics_increments_on_requests(obs_client):
    """Making HTTP requests increments the Prometheus request counter."""
    with patch.object(settings, "METRICS_ENABLED", True), \
         patch.object(settings, "METRICS_AUTH_TOKEN", None):
        resp = obs_client.get("/api/health/live")
        assert resp.status_code == 200
        metrics_resp = obs_client.get("/api/v1/metrics")
        assert metrics_resp.status_code == 200
        metrics_text = metrics_resp.text
        assert 'handler="/api/health/live"' in metrics_text
        assert 'method="GET"' in metrics_text
        assert 'status_class="2xx"' in metrics_text


# ==============================================================================
# 3. SECURITY HEADERS TESTS
# ==============================================================================

def test_owasp_security_headers_present(obs_client):
    """Responses contain all baseline OWASP security headers."""
    response = obs_client.get("/api/health")
    assert response.status_code == 200
    headers = response.headers
    assert headers.get("X-Content-Type-Options") == "nosniff"
    assert headers.get("X-Frame-Options") == "SAMEORIGIN"
    assert headers.get("X-XSS-Protection") == "1; mode=block"
    assert headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"


def test_permissions_policy_header_present(obs_client):
    """Responses contain configured Permissions-Policy header."""
    response = obs_client.get("/api/health")
    assert response.status_code == 200
    assert "camera=()" in response.headers.get("Permissions-Policy", "")
    assert "microphone=()" in response.headers.get("Permissions-Policy", "")


def test_csp_report_only_by_default(obs_client):
    """By default, Content-Security-Policy-Report-Only is used for safe rollout."""
    response = obs_client.get("/api/health")
    assert response.status_code == 200
    assert "Content-Security-Policy-Report-Only" in response.headers
    assert "Content-Security-Policy" not in response.headers
    csp_val = response.headers["Content-Security-Policy-Report-Only"]
    assert "default-src 'self'" in csp_val
    assert "https://fonts.googleapis.com" in csp_val
    assert "https://fonts.gstatic.com" in csp_val


def test_csp_enforcing_mode(obs_client):
    """When SECURE_CSP_REPORT_ONLY is False, enforcing Content-Security-Policy is used."""
    with patch.object(settings, "SECURE_CSP_REPORT_ONLY", False):
        response = obs_client.get("/api/health")
        assert response.status_code == 200
        assert "Content-Security-Policy" in response.headers
        assert "Content-Security-Policy-Report-Only" not in response.headers


def test_hsts_disabled_when_zero(obs_client):
    """When SECURE_HSTS_SECONDS is 0 (default), Strict-Transport-Security header is omitted."""
    with patch.object(settings, "SECURE_HSTS_SECONDS", 0):
        response = obs_client.get("/api/health")
        assert response.status_code == 200
        assert "Strict-Transport-Security" not in response.headers


def test_hsts_enabled_when_positive(obs_client):
    """When SECURE_HSTS_SECONDS > 0, Strict-Transport-Security is attached."""
    with patch.object(settings, "SECURE_HSTS_SECONDS", 31536000):
        with patch.object(settings, "SECURE_HSTS_INCLUDE_SUBDOMAINS", True):
            with patch.object(settings, "SECURE_HSTS_PRELOAD", True):
                response = obs_client.get("/api/health")
                assert response.status_code == 200
                hsts = response.headers.get("Strict-Transport-Security", "")
                assert "max-age=31536000" in hsts
                assert "includeSubDomains" in hsts
                assert "preload" in hsts


def test_scheduler_metrics():
    """Verify continuous intelligence scheduler metrics are recorded and exported."""
    from app.core.metrics import (
        SCHEDULER_BUSINESSES_SCANNED_TOTAL,
        SCHEDULER_SCANS_RECONCILED_TOTAL,
        SCHEDULER_TICK_DURATION_SECONDS,
        SCHEDULER_TICKS_TOTAL,
        get_latest_metrics,
    )

    SCHEDULER_TICKS_TOTAL.labels(status="success").inc()
    SCHEDULER_TICK_DURATION_SECONDS.observe(0.123)
    SCHEDULER_SCANS_RECONCILED_TOTAL.inc(5)
    SCHEDULER_BUSINESSES_SCANNED_TOTAL.inc(3)

    metrics_text = get_latest_metrics().decode("utf-8")
    assert "nexus_scheduler_ticks_total" in metrics_text
    assert "nexus_scheduler_tick_duration_seconds" in metrics_text
    assert "nexus_scheduler_scans_reconciled_total" in metrics_text
    assert "nexus_scheduler_businesses_scanned_total" in metrics_text
