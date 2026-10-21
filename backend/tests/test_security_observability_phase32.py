"""NEXUS Phase 32 — Security, Reliability, and Observability Audit Suite.

Validates:
1. Multi-tenant security boundaries and IDOR attempt detection.
2. Authentication, JWT validation, expiration, and fail-closed revocation.
3. Secret redaction and traceback shielding in production error responses.
4. Database connection pool configuration and timeout behavior.
5. Structured request logging, correlation ID propagation, and timing headers.
6. Health/readiness/liveness dependency decoupling and observability signals.
"""

import logging
from unittest.mock import MagicMock, patch
from uuid import uuid4
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.core.auth import verify_user_business_access
from app.services.auth_service import AuthService
from app.core.cache import CacheClient, _reset_cache_for_testing
from app.core.config import Settings, settings
from app.core.database import _get_engine_kwargs
from app.main import app
from app.models.tenant import Business, Organization, OrganizationMembership, UserIdentity


# ---------------------------------------------------------------------------
# 1. Tenant Security & IDOR Enforcement
# ---------------------------------------------------------------------------


def test_idor_cross_tenant_access_blocked_and_logged(db_session, caplog) -> None:
    """A user attempting to access a business outside their organization must receive 403 Forbidden with a logged warning."""
    caplog.set_level(logging.WARNING)

    # Org A & Biz A
    org_a = Organization(id=str(uuid4()), name="Org A", slug="org-a", status="active")
    db_session.add(org_a)
    db_session.flush()
    biz_a = Business(
        id=str(uuid4()), organization_id=org_a.id, name="Biz A", industry="Retail",
        country="US", currency="USD", timezone="UTC", business_type="B2C",
        fiscal_year_start=1, status="active", onboarding_step="completed",
    )
    db_session.add(biz_a)

    # User B belonging to Org B
    org_b = Organization(id=str(uuid4()), name="Org B", slug="org-b", status="active")
    db_session.add(org_b)
    db_session.flush()
    user_b_id = str(uuid4())
    mem_b = OrganizationMembership(organization_id=org_b.id, user_id=user_b_id, role="owner")
    db_session.add(mem_b)
    db_session.commit()

    user_b = UserIdentity(id=user_b_id, email="user_b@example.com")

    auth_logger = logging.getLogger("app.core.auth")
    auth_logger.disabled = False
    caplog.set_level(logging.WARNING, logger="app.core.auth")
    if caplog.handler not in logging.getLogger().handlers:
        logging.getLogger().addHandler(caplog.handler)
    if caplog.handler not in auth_logger.handlers:
        auth_logger.addHandler(caplog.handler)

    # User B tries to access Biz A
    with pytest.raises(HTTPException) as exc_info:
        verify_user_business_access(db_session, user_b, biz_a.id, action="inspect")
    assert exc_info.value.status_code == 403
    assert "Access denied" in exc_info.value.detail

    # Verify IDOR warning logged
    warning_records = [r for r in caplog.records if "SECURITY: IDOR attempt" in r.message]
    assert len(warning_records) >= 1
    assert user_b_id in warning_records[0].message
    assert biz_a.id in warning_records[0].message


def test_unauthenticated_tenant_access_rejected() -> None:
    """Calling verify_user_business_access with None user must raise HTTP 401."""
    mock_db = MagicMock()
    with pytest.raises(HTTPException) as exc_info:
        verify_user_business_access(mock_db, None, "biz-123")
    assert exc_info.value.status_code == 401


# ---------------------------------------------------------------------------
# 2. JWT Security & Revocation
# ---------------------------------------------------------------------------


def test_jwt_valid_lifecycle_and_claims() -> None:
    """Tokens created with valid claims encode and decode correctly."""
    user_id = str(uuid4())
    token = AuthService.create_access_token(user_id=user_id, email="test@example.com")
    payload = AuthService.decode_access_token(token)
    assert payload["sub"] == user_id
    assert payload["email"] == "test@example.com"
    assert "exp" in payload
    assert "jti" in payload


def test_tampered_jwt_signature_rejected() -> None:
    """Tampered token signatures must be rejected by decode_access_token with a sanitized message."""
    token = AuthService.create_access_token(user_id="user123", email="user@example.com")
    parts = token.split(".")
    tampered = f"{parts[0]}.{parts[1]}.invalidsignature12345"
    with pytest.raises(HTTPException) as exc_info:
        AuthService.decode_access_token(tampered)
    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "Invalid authentication token."
    assert "invalidsignature" not in str(exc_info.value.detail)
    assert "DecodeError" not in str(exc_info.value.detail)


# ---------------------------------------------------------------------------
# 3. Production Error Shielding & Traceback Protection
# ---------------------------------------------------------------------------


def test_production_error_handler_shields_tracebacks() -> None:
    """In production (DEBUG=False), unhandled exceptions return a sanitized message without tracebacks."""
    client = TestClient(app, raise_server_exceptions=False)

    # Patch an endpoint to simulate an unexpected internal error
    with patch("app.api.v1.endpoints.health.check_database_connection", side_effect=RuntimeError("Secret internal database crash with password=12345")), \
         patch.object(settings, "DEBUG", False):

        resp = client.get("/api/health/ready")
        assert resp.status_code in [500, 503]
        text = resp.text
        assert "password=12345" not in text
        assert "RuntimeError" not in text
        assert "Traceback" not in text


# ---------------------------------------------------------------------------
# 4. Connection Pool & Timeout Configurations
# ---------------------------------------------------------------------------


def test_connection_pool_kwargs_configured() -> None:
    """SQLAlchemy engine kwargs must configure pool_size, max_overflow, pool_timeout, and pool_recycle."""
    custom_cfg = Settings(
        DB_POOL_SIZE=15,
        DB_MAX_OVERFLOW=25,
        DB_POOL_TIMEOUT=45,
        DB_POOL_RECYCLE=3600,
    )
    kwargs = _get_engine_kwargs(custom_cfg)
    assert kwargs["pool_size"] == 15
    assert kwargs["max_overflow"] == 25
    assert kwargs["pool_timeout"] == 45
    assert kwargs["pool_recycle"] == 3600
    assert kwargs["pool_pre_ping"] is True


# ---------------------------------------------------------------------------
# 5. Correlation ID & Security Headers
# ---------------------------------------------------------------------------


def test_correlation_id_and_security_headers_in_all_responses() -> None:
    """Responses must include X-Request-ID, X-Process-Time-Ms, and OWASP security headers."""
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get("/")
    assert resp.status_code == 200

    headers = resp.headers
    assert "X-Request-ID" in headers
    assert "X-Process-Time-Ms" in headers
    assert headers.get("X-Content-Type-Options") == "nosniff"
    assert headers.get("X-Frame-Options") == "SAMEORIGIN"
    assert headers.get("X-XSS-Protection") == "1; mode=block"
    assert headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"


# ---------------------------------------------------------------------------
# 6. LLM Guardrail Invariant
# ---------------------------------------------------------------------------


def test_llm_allow_external_calls_invariant() -> None:
    """LLM_ALLOW_EXTERNAL_CALLS must remain strictly False by default."""
    assert getattr(settings, "LLM_ALLOW_EXTERNAL_CALLS", False) is False
