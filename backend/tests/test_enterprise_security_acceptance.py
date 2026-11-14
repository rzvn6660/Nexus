"""Enterprise Security Audit & Vulnerability Remediation Acceptance Tests.

Regression test suite verifying remediations for verified vulnerabilities:
1. [VULN-AUTH-01]: Unauthenticated anonymous access and cross-tenant data exposure
   in diagnostic investigation (/investigations/analyze) and predictive forecasting (/forecasts).
2. [VULN-SSRF-01]: Server-Side Request Forgery (SSRF) and broken function-level authorization
   in PostgreSQL database onboarding (/api/v1/analyst/onboard/postgres/*).
3. [VULN-NET-01]: Rate limit bypass via client-controlled X-Forwarded-For spoofing.
4. [VULN-PULSE-01]: Missing authorization parameters in PulseService.get_report_pdf and get_report.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from app.analytics.onboarding.postgres_service import PostgreSQLOnboardingService
from app.analytics.pulse.service import PulseService
from app.core.rate_limit import get_client_ip
from app.models.pulse import PulseGeneratedReport
from app.models.tenant import (
    OrganizationMembership,
    UserIdentity,
)
from app.services.auth_service import AuthService
from fastapi import Request
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session


@pytest.fixture
def enterprise_security_fixture(db_session: Session):
    """Seed two distinct isolated tenants and a non-admin user for role testing."""
    # Tenant Alpha (Elena - Owner)
    user_alpha, org_alpha, biz_alpha = AuthService.signup(
        db=db_session,
        email="elena.sec@alphacorp.com",
        password="SecurePassword123!",
        full_name="Elena Alpha",
        organization_name="Alpha Corp Sec",
        business_name="Alpha Retail Sec",
    )
    token_alpha = AuthService.create_access_token(
        user_id=user_alpha.id,
        email=user_alpha.email,
        organization_id=org_alpha.id,
        business_id=biz_alpha.id,
    )

    # Tenant Beta (Marcus - Owner)
    user_beta, org_beta, biz_beta = AuthService.signup(
        db=db_session,
        email="marcus.sec@betacorp.com",
        password="SecurePassword123!",
        full_name="Marcus Beta",
        organization_name="Beta Corp Sec",
        business_name="Beta Logistics Sec",
    )
    token_beta = AuthService.create_access_token(
        user_id=user_beta.id,
        email=user_beta.email,
        organization_id=org_beta.id,
        business_id=biz_beta.id,
    )

    # Non-admin viewer in Tenant Alpha (Viewer role)
    viewer_user = UserIdentity(
        id=f"usr_viewer_{uuid4().hex[:8]}",
        email="viewer.sec@alphacorp.com",
        password_hash=user_alpha.password_hash,
        full_name="Viewer User",
        is_active=True,
    )
    db_session.add(viewer_user)
    db_session.flush()

    viewer_membership = OrganizationMembership(
        user_id=viewer_user.id,
        organization_id=org_alpha.id,
        role="viewer",
    )
    db_session.add(viewer_membership)
    db_session.commit()

    token_viewer = AuthService.create_access_token(
        user_id=viewer_user.id,
        email=viewer_user.email,
        organization_id=org_alpha.id,
        business_id=biz_alpha.id,
    )

    return {
        "user_alpha": user_alpha,
        "biz_alpha": biz_alpha,
        "token_alpha": token_alpha,
        "user_beta": user_beta,
        "biz_beta": biz_beta,
        "token_beta": token_beta,
        "viewer_user": viewer_user,
        "token_viewer": token_viewer,
    }


# ==============================================================================
# 1. [VULN-AUTH-01]: UNICAST / ANONYMOUS AUTHENTICATION & IDOR ENFORCEMENT
# ==============================================================================

def test_anonymous_request_rejected_on_investigation(api_client: TestClient):
    """Anonymous request to POST /api/v1/investigation/analyze must receive 401 Unauthorized."""
    res = api_client.post(
        "/api/v1/investigation/analyze",
        json={"query": "Why did revenue drop in Q1?"},
    )
    assert res.status_code == 401
    assert "Authentication credentials required" in res.json()["detail"]


def test_anonymous_request_rejected_on_forecast_analyze(api_client: TestClient):
    """Anonymous request to POST /api/v1/forecast/analyze must receive 401 Unauthorized."""
    res = api_client.post(
        "/api/v1/forecast/analyze",
        json={"query": "Forecast revenue for next 3 months"},
    )
    assert res.status_code == 401
    assert "Authentication credentials required" in res.json()["detail"]


def test_anonymous_request_rejected_on_forecast_structured(api_client: TestClient):
    """Anonymous request to POST /api/v1/forecast must receive 401 Unauthorized."""
    res = api_client.post(
        "/api/v1/forecast",
        json={
            "target_metric": "sales",
            "forecast_horizon": 2,
            "frequency": "monthly",
            "model_policy": "validated_best",
        },
    )
    assert res.status_code == 401
    assert "Authentication credentials required" in res.json()["detail"]


def test_cross_tenant_idor_rejected_on_investigation(api_client: TestClient, enterprise_security_fixture):
    """Marcus cannot access Elena's business investigation by forging X-Business-ID (403 Forbidden)."""
    forged_headers = {
        "Authorization": f"Bearer {enterprise_security_fixture['token_beta']}",
        "X-Business-ID": enterprise_security_fixture["biz_alpha"].id,
    }
    res = api_client.post(
        "/api/v1/investigation/analyze",
        json={"query": "Why did revenue drop in Q1?"},
        headers=forged_headers,
    )
    assert res.status_code == 403
    assert "Access denied" in res.json()["detail"]


def test_cross_tenant_idor_rejected_on_forecast(api_client: TestClient, enterprise_security_fixture):
    """Marcus cannot generate forecasts for Elena's business by forging X-Business-ID (403 Forbidden)."""
    forged_headers = {
        "Authorization": f"Bearer {enterprise_security_fixture['token_beta']}",
        "X-Business-ID": enterprise_security_fixture["biz_alpha"].id,
    }
    res = api_client.post(
        "/api/v1/forecast/analyze",
        json={"query": "Forecast revenue for next 3 months"},
        headers=forged_headers,
    )
    assert res.status_code == 403
    assert "Access denied" in res.json()["detail"]


# ==============================================================================
# 2. [VULN-SSRF-01]: SERVER-SIDE REQUEST FORGERY & ROLE AUTHORIZATION DEFENSE
# ==============================================================================

def test_ssrf_cloud_metadata_strictly_blocked():
    """Cloud metadata endpoints (169.254.169.254) are unconditionally blocked."""
    with pytest.raises(ValueError, match="cloud metadata"):
        PostgreSQLOnboardingService.validate_safe_external_host("169.254.169.254", allow_local_for_testing=False)

    with pytest.raises(ValueError, match="cloud metadata"):
        PostgreSQLOnboardingService.validate_safe_external_host("169.254.169.254", allow_local_for_testing=True)

    with pytest.raises(ValueError, match="cloud metadata"):
        PostgreSQLOnboardingService.validate_safe_external_host("metadata.google.internal")


def test_ssrf_private_and_loopback_ips_blocked():
    """Loopback, RFC1918 private IPs, and internal container hostnames are blocked in production mode."""
    blocked_targets = [
        "127.0.0.1",
        "localhost",
        "10.0.0.1",
        "172.16.0.1",
        "192.168.1.50",
        "nexus_postgres_staging",
        "nexus_postgres",
        "postgres",
        "nexus_redis_staging",
        "redis",
    ]
    for target in blocked_targets:
        with pytest.raises(ValueError):
            PostgreSQLOnboardingService.validate_safe_external_host(target, allow_local_for_testing=False)


def test_ssrf_blocked_on_http_api_test_endpoint(api_client: TestClient, enterprise_security_fixture):
    """HTTP POST /api/v1/analyst/onboard/postgres/test blocks attempts to probe cloud metadata or internal network."""
    headers = {
        "Authorization": f"Bearer {enterprise_security_fixture['token_alpha']}",
        "X-Business-ID": enterprise_security_fixture["biz_alpha"].id,
    }
    # 1. Cloud metadata
    res_metadata = api_client.post(
        "/api/v1/analyst/onboard/postgres/test",
        json={
            "host": "169.254.169.254",
            "port": 5432,
            "database": "db",
            "user": "usr",
            "password": "pwd",
        },
        headers=headers,
    )
    assert res_metadata.status_code == 200
    data = res_metadata.json()
    assert data["success"] is False
    assert "cloud metadata" in data["error"].lower() or "prohibited" in data["error"].lower()

    # 2. Local loopback probe
    res_loopback = api_client.post(
        "/api/v1/analyst/onboard/postgres/test",
        json={
            "host": "127.0.0.1",
            "port": 5432,
            "database": "db",
            "user": "usr",
            "password": "pwd",
        },
        headers=headers,
    )
    assert res_loopback.status_code == 200
    assert res_loopback.json()["success"] is False


def test_postgres_onboard_requires_owner_or_admin_role(api_client: TestClient, enterprise_security_fixture):
    """Non-admin viewer users are rejected with 403 Forbidden on database onboarding endpoints."""
    viewer_headers = {
        "Authorization": f"Bearer {enterprise_security_fixture['token_viewer']}",
        "X-Business-ID": enterprise_security_fixture["biz_alpha"].id,
    }
    payload = {
        "host": "93.184.216.34",
        "port": 5432,
        "database": "ext_db",
        "user": "ext_user",
        "password": "ext_password",
    }

    # /test
    res_test = api_client.post("/api/v1/analyst/onboard/postgres/test", json=payload, headers=viewer_headers)
    assert res_test.status_code == 403
    assert "Administrative privilege required" in res_test.json()["detail"]

    # /inspect
    res_inspect = api_client.post("/api/v1/analyst/onboard/postgres/inspect", json=payload, headers=viewer_headers)
    assert res_inspect.status_code == 403
    assert "Administrative privilege required" in res_inspect.json()["detail"]

    # /preview
    preview_payload = dict(payload)
    preview_payload["table_name"] = "orders"
    res_preview = api_client.post("/api/v1/analyst/onboard/postgres/preview", json=preview_payload, headers=viewer_headers)
    assert res_preview.status_code == 403
    assert "Administrative privilege required" in res_preview.json()["detail"]


# ==============================================================================
# 3. [VULN-NET-01]: RATE LIMIT CLIENT IP SPOOFING DEFENSE & TRUSTED PROXY CHAIN
# ==============================================================================

def test_rate_limiter_rejects_spoofed_headers_from_untrusted_direct_peer(monkeypatch):
    """Direct untrusted peer cannot spoof X-Real-IP or X-Forwarded-For to evade rate limits."""
    from app.core.config import settings
    monkeypatch.setattr(settings, "TRUSTED_PROXIES", ["127.0.0.1", "::1"])

    mock_request = MagicMock(spec=Request)
    mock_request.client.host = "198.51.100.55"  # Direct external client (untrusted)
    mock_request.headers = {
        "X-Real-IP": "1.2.3.4",
        "X-Forwarded-For": "5.6.7.8, 9.10.11.12",
    }

    # Forwarded headers MUST be ignored because peer is not in TRUSTED_PROXIES
    resolved_ip = get_client_ip(mock_request)
    assert resolved_ip == "198.51.100.55"


def test_rate_limiter_prioritizes_trusted_x_real_ip(monkeypatch):
    """When direct connection is from a trusted proxy, X-Real-IP is accepted."""
    from app.core.config import settings
    monkeypatch.setattr(settings, "TRUSTED_PROXIES", ["127.0.0.1", "::1"])

    mock_request = MagicMock(spec=Request)
    mock_request.client.host = "127.0.0.1"  # Local reverse proxy (Nginx)
    mock_request.headers = {
        "X-Real-IP": "203.0.113.195",
    }

    resolved_ip = get_client_ip(mock_request)
    assert resolved_ip == "203.0.113.195"


def test_rate_limiter_extracts_rightmost_x_forwarded_for(monkeypatch):
    """When evaluated through trusted proxies, right-most untrusted client IP is extracted."""
    from app.core.config import settings
    # 127.0.0.1 and 10.0.0.2 are trusted internal proxies
    monkeypatch.setattr(settings, "TRUSTED_PROXIES", ["127.0.0.1", "10.0.0.2", "::1"])

    mock_request = MagicMock(spec=Request)
    mock_request.client.host = "127.0.0.1"  # Immediate proxy hop
    mock_request.headers = {
        "X-Forwarded-For": "198.51.100.1, 203.0.113.200, 10.0.0.2",
    }

    # 10.0.0.2 is in TRUSTED_PROXIES, so step back to 203.0.113.200 (first untrusted hop)
    resolved_ip = get_client_ip(mock_request)
    assert resolved_ip == "203.0.113.200"


def test_rate_limiter_rejects_malformed_ip_strings(monkeypatch):
    """Malformed or injection strings in IP headers are rejected and fall back safely."""
    from app.core.config import settings
    monkeypatch.setattr(settings, "TRUSTED_PROXIES", ["127.0.0.1"])

    mock_request = MagicMock(spec=Request)
    mock_request.client.host = "127.0.0.1"
    mock_request.headers = {
        "X-Real-IP": "attacker_injection_key; DROP TABLE users;",
        "X-Forwarded-For": "bad_ip_format",
    }

    resolved_ip = get_client_ip(mock_request)
    assert resolved_ip == "127.0.0.1"


def test_rate_limiter_handles_ipv6_and_no_forwarded_headers(monkeypatch):
    """Direct IPv6 requests without forwarded headers resolve cleanly."""
    from app.core.config import settings
    monkeypatch.setattr(settings, "TRUSTED_PROXIES", ["127.0.0.1"])

    mock_request = MagicMock(spec=Request)
    mock_request.client.host = "2001:db8::dead:beef"
    mock_request.headers = {}

    resolved_ip = get_client_ip(mock_request)
    assert resolved_ip == "2001:db8::dead:beef"


def test_rate_limiter_with_no_trusted_proxies_deployment(monkeypatch):
    """When TRUSTED_PROXIES is empty, all forwarded headers are rejected."""
    from app.core.config import settings
    monkeypatch.setattr(settings, "TRUSTED_PROXIES", [])

    mock_request = MagicMock(spec=Request)
    mock_request.client.host = "127.0.0.1"
    mock_request.headers = {
        "X-Real-IP": "203.0.113.5",
        "X-Forwarded-For": "203.0.113.6",
    }

    # With no trusted proxies, direct peer IP is returned
    resolved_ip = get_client_ip(mock_request)
    assert resolved_ip == "127.0.0.1"


def test_rate_limiter_resolves_trusted_proxy_hostname(monkeypatch):
    """When a proxy hostname (e.g. 'frontend') is in TRUSTED_PROXIES, its resolved IP is trusted."""
    from app.core.config import settings
    monkeypatch.setattr(settings, "TRUSTED_PROXIES", ["frontend", "127.0.0.1"])

    # Mock getaddrinfo for 'frontend' resolving to 172.19.0.5 (actual Docker Compose container IP)
    monkeypatch.setattr(
        "socket.getaddrinfo",
        lambda host, port, proto=0: [
            (2, 1, 6, "", ("172.19.0.5", 0)),
        ] if host == "frontend" else [],
    )

    mock_request = MagicMock(spec=Request)
    mock_request.client.host = "172.19.0.5"  # Direct connection from Nginx frontend container
    mock_request.headers = {
        "X-Real-IP": "203.0.113.111",
    }

    resolved_ip = get_client_ip(mock_request)
    assert resolved_ip == "203.0.113.111"


def test_rate_limiter_does_not_trust_entire_private_network(monkeypatch):
    """Unapproved container IPs on the Docker bridge cannot spoof headers when proxy is explicitly pinned."""
    from app.core.config import settings
    # Explicitly trust ONLY the frontend container IP and loopback
    monkeypatch.setattr(settings, "TRUSTED_PROXIES", ["172.19.0.5", "127.0.0.1"])

    mock_request = MagicMock(spec=Request)
    mock_request.client.host = "172.19.0.99"  # Rogue internal container
    mock_request.headers = {
        "X-Real-IP": "1.2.3.4",
        "X-Forwarded-For": "5.6.7.8",
    }

    # Must NOT trust 172.19.0.99; forwarded headers must be ignored
    resolved_ip = get_client_ip(mock_request)
    assert resolved_ip == "172.19.0.99"


# ==============================================================================
# 4. [SSRF-01 ADVANCED]: IP PINNING, PROHIBITED PORTS & DNS REBINDING DEFENSE
# ==============================================================================

def test_ssrf_ipv4_mapped_ipv6_blocked():
    """IPv4-mapped IPv6 cloud metadata and loopback addresses are strictly blocked."""
    with pytest.raises(ValueError, match="cloud metadata"):
        PostgreSQLOnboardingService.validate_safe_external_host("::ffff:169.254.169.254", allow_local_for_testing=False)

    with pytest.raises(ValueError, match="loopback"):
        PostgreSQLOnboardingService.validate_safe_external_host("::ffff:127.0.0.1", allow_local_for_testing=False)


def test_ssrf_prohibited_ports_blocked():
    """Sensitive infrastructure ports (SSH, Docker, Redis, HTTP) are blocked for database onboarding."""
    for prohibited_port in [22, 80, 443, 2375, 6379]:
        with pytest.raises(ValueError, match=f"Port {prohibited_port} is prohibited"):
            PostgreSQLOnboardingService.validate_safe_external_host("93.184.216.34", port=prohibited_port, allow_local_for_testing=False)


def test_ssrf_malformed_hostnames_rejected():
    """Malformed hostnames, URL schemes, and path traversal strings are rejected."""
    malformed_targets = [
        "http://evil.com",
        "postgres://user:pass@evil.com",
        "evil.com/path",
        "evil.com?query=1",
        "user@evil.com",
    ]
    for target in malformed_targets:
        with pytest.raises(ValueError, match="invalid characters or URL components|URL scheme"):
            PostgreSQLOnboardingService.validate_safe_external_host(target, allow_local_for_testing=False)


def test_ssrf_ip_pinning_prevents_dns_rebinding(monkeypatch):
    """_build_connection_string pins connection to validated IP via hostaddr to defeat DNS rebinding."""
    # Mock getaddrinfo to return a safe public IP
    monkeypatch.setattr(
        "socket.getaddrinfo",
        lambda host, port, proto=0: [
            (2, 1, 6, "", ("93.184.216.34", 5432)),
        ],
    )
    conn_str = PostgreSQLOnboardingService._build_connection_string(
        host="safe-merchant-db.example.com",
        port=5432,
        database="orders_db",
        user="db_user",
        password="secret_password",
        allow_local_for_testing=False,
    )
    # Must specify host for TLS certificate verification AND hostaddr for socket destination
    assert "host='safe-merchant-db.example.com'" in conn_str
    assert "hostaddr='93.184.216.34'" in conn_str


def test_ssrf_production_env_strictly_disallows_local_exceptions(monkeypatch):
    """When APP_ENV is production, local loopback exceptions are strictly prohibited."""
    from app.core.config import settings
    monkeypatch.setattr(settings, "APP_ENV", "production")

    # Even if allow_local_for_testing is passed as True, production must override and block
    with pytest.raises(ValueError, match="loopback"):
        PostgreSQLOnboardingService.validate_safe_external_host("127.0.0.1", allow_local_for_testing=True)


def test_ssrf_hostaddr_parameter_injection_blocked():
    """Attempting to inject raw hostaddr keys in database or user parameters is strictly rejected."""
    with pytest.raises(ValueError, match="contains illegal keywords"):
        PostgreSQLOnboardingService._build_connection_string(
            host="93.184.216.34",
            port=5432,
            database="valid_db hostaddr=169.254.169.254",
            user="valid_user",
            password="valid_password",
            allow_local_for_testing=False,
        )


# ==============================================================================
# 5. [VULN-PULSE-01]: PULSE SERVICE AUTHORIZATION PARAMETER ENFORCEMENT
# ==============================================================================

def test_pulse_service_get_report_pdf_requires_authorization(db_session: Session, enterprise_security_fixture):
    """PulseService.get_report_pdf fails closed if neither business_id nor access_token is provided."""
    biz = enterprise_security_fixture["biz_alpha"]
    report = PulseGeneratedReport(
        id=f"rep_{uuid4().hex[:8]}",
        business_id=biz.id,
        organization_id=enterprise_security_fixture["user_alpha"].id,
        report_title="Confidential Audit Report",
        report_type="executive_monthly",
        period_start=datetime.now(UTC),
        period_end=datetime.now(UTC),
        kpi_payload={},
        insights_json=[],
        executive_summary="Executive summary text.",
        messaging_summary="Messaging summary text.",
        watermark_status="verified_complete",
        pdf_file_bytes=b"%PDF-1.4 test bytes",
        access_token="secret_token_123",
        token_expires_at=datetime.now(UTC) + timedelta(days=30),
    )
    db_session.add(report)
    db_session.commit()

    # Calling without both business_id and access_token must raise PermissionError
    with pytest.raises(PermissionError, match="Authorization required"):
        PulseService.get_report_pdf(db_session, report_id=report.id, business_id=None, access_token=None)

    # Calling with valid business_id succeeds
    pdf_bytes, _ = PulseService.get_report_pdf(db_session, report_id=report.id, business_id=biz.id)
    assert pdf_bytes == b"%PDF-1.4 test bytes"

    # Calling with foreign business_id fails
    with pytest.raises(PermissionError, match="Access denied"):
        PulseService.get_report_pdf(db_session, report_id=report.id, business_id=enterprise_security_fixture["biz_beta"].id)

    # Calling with valid access_token succeeds
    pdf_bytes2, _ = PulseService.get_report_pdf(db_session, report_id=report.id, access_token="secret_token_123")
    assert pdf_bytes2 == b"%PDF-1.4 test bytes"


def test_pulse_service_get_report_requires_authorization(db_session: Session, enterprise_security_fixture):
    """PulseService.get_report fails closed if neither business_id nor access_token is provided."""
    biz = enterprise_security_fixture["biz_alpha"]
    report = PulseGeneratedReport(
        id=f"rep_{uuid4().hex[:8]}",
        business_id=biz.id,
        organization_id=enterprise_security_fixture["user_alpha"].id,
        report_title="Confidential Pulse Report",
        report_type="executive_monthly",
        period_start=datetime.now(UTC),
        period_end=datetime.now(UTC),
        access_token="secret_token_456",
        token_expires_at=datetime.now(UTC) + timedelta(days=30),
        kpi_payload={},
        insights_json=[],
        executive_summary="Summary",
        messaging_summary="Msg",
        watermark_status="verified_complete",
    )
    db_session.add(report)
    db_session.commit()

    # Calling without both business_id and access_token must raise PermissionError
    with pytest.raises(PermissionError, match="Authorization required"):
        PulseService.get_report(db_session, report_id=report.id, business_id=None, access_token=None)


def test_pulse_service_expired_token_rejected(db_session: Session, enterprise_security_fixture):
    """PulseService rejects expired report access tokens."""
    biz = enterprise_security_fixture["biz_alpha"]
    report = PulseGeneratedReport(
        id=f"rep_{uuid4().hex[:8]}",
        business_id=biz.id,
        organization_id=enterprise_security_fixture["user_alpha"].id,
        report_title="Expired Token Report",
        report_type="executive_monthly",
        period_start=datetime.now(UTC) - timedelta(days=60),
        period_end=datetime.now(UTC) - timedelta(days=30),
        access_token="expired_token_789",
        token_expires_at=datetime.now(UTC) - timedelta(days=1),  # Expired yesterday
        kpi_payload={},
        insights_json=[],
        executive_summary="Summary",
        messaging_summary="Msg",
        watermark_status="verified_complete",
    )
    db_session.add(report)
    db_session.commit()

    # Expired token raises ValueError
    with pytest.raises(ValueError, match="expired"):
        PulseService.get_report(db_session, report_id=report.id, access_token="expired_token_789")


# ==============================================================================
# 6. IDENTITY LIFECYCLE & TOKEN REVOCATION INTEGRITY
# ==============================================================================

def test_auth_deactivated_user_blocked_on_api(api_client: TestClient, db_session: Session, enterprise_security_fixture):
    """Deactivated user account is immediately blocked with HTTP 403."""
    user = enterprise_security_fixture["user_alpha"]
    user.is_active = False
    db_session.commit()

    headers = {
        "Authorization": f"Bearer {enterprise_security_fixture['token_alpha']}",
        "X-Business-ID": enterprise_security_fixture["biz_alpha"].id,
    }
    res = api_client.post("/api/v1/investigation/analyze", json={"query": "Test"}, headers=headers)
    assert res.status_code == 403
    assert "deactivated" in res.json()["detail"].lower()

    # Restore user active status for subsequent tests
    user.is_active = True
    db_session.commit()


def test_auth_revoked_token_blocked_on_api(api_client: TestClient, enterprise_security_fixture):
    """Revoked token JTI is blocked with HTTP 401."""
    token = enterprise_security_fixture["token_alpha"]
    payload = AuthService.decode_access_token(token)
    jti = payload.get("jti")
    AuthService.revoke_token(jti)

    headers = {
        "Authorization": f"Bearer {token}",
        "X-Business-ID": enterprise_security_fixture["biz_alpha"].id,
    }
    res = api_client.post("/api/v1/investigation/analyze", json={"query": "Test"}, headers=headers)
    assert res.status_code == 401
    assert "revoked" in res.json()["detail"].lower()
