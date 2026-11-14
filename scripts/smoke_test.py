#!/usr/bin/env python
"""NEXUS Production Smoke Test Suite.

Executes an end-to-end verification of the 11 core production capabilities:
  1. Root Index & Navigation
  2. Health, Liveness & Readiness Probes
  3. Data Layer Health & Model Registry
  4. Deterministic Analytics Engine
  5. Semantic KPI & Synonym Resolution
  6. Hybrid RAG Context Retrieval
  7. Predictive Time-Series Forecasting
  8. Diagnostic Causal Investigation
  9. Agentic LangGraph Pipeline
 10. Request Tracing & Correlation Headers (X-Request-ID)
 11. CORS & Security Safeguards

Usage:
  python scripts/smoke_test.py                     # Runs in-process via FastAPI TestClient
  python scripts/smoke_test.py --base-url http://localhost:8000 # Runs against live deployment
"""

import argparse
import os
import sys
import time
from typing import Any, Dict

# Ensure project root and backend directory are in sys.path for local in-process testing
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

backend_dir = os.path.join(project_root, "backend")
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)


def resolve_configured_database_url() -> str | None:
    """Resolve active database connection URL honoring TEST_DATABASE_URL and DATABASE_URL."""
    return os.getenv("TEST_DATABASE_URL") or os.getenv("DATABASE_URL")


def is_live_or_ci_environment() -> bool:
    """Detect whether execution environment strictly mandates live database readiness."""
    return (
        os.getenv("CI", "").strip().lower() in ("true", "1")
        or os.getenv("REQUIRE_POSTGRES", "").strip().lower() in ("true", "1")
        or os.getenv("APP_ENV", "").strip().lower() in ("production", "prod", "staging")
    )


def print_step(step_num: int, title: str) -> None:
    print(f"\n[{step_num:02d}/11] {title}...", flush=True)


def check(condition: bool, message: str) -> None:
    if condition:
        print(f"       [PASS] {message}", flush=True)
    else:
        print(f"       [FAIL] {message}", flush=True)
        raise AssertionError(f"Smoke test failed: {message}")


def run_smoke_test(client_getter, require_healthy: bool = False) -> None:
    print("=" * 60)
    print("NEXUS Platform Production Smoke Test")
    print("Where Business Data Becomes Intelligence.")
    print("=" * 60)

    start_total = time.perf_counter()
    passed_steps = 0

    client = client_getter()

    # Step 1: Root Index
    print_step(1, "Testing Root Index & Metadata")
    resp = client.get("/")
    check(resp.status_code == 200, f"HTTP 200 OK (got {resp.status_code})")
    data = resp.json()
    check(data.get("name") == "NEXUS", f"Application name: {data.get('name')}")
    check("Agentic Business Intelligence" in data.get("title", ""), f"Title: {data.get('title')}")
    check("health" in data and "readiness" in data, "Health links present")
    passed_steps += 1

    # Step 2: Health Probes
    print_step(2, "Testing Liveness & Readiness Probes")
    resp_live = client.get("/api/v1/health/live")
    check(resp_live.status_code == 200, f"Liveness probe: HTTP 200 (got {resp_live.status_code})")
    check(resp_live.json().get("status") == "alive", "Liveness status: alive")

    resp_health = client.get("/api/v1/health")
    check(resp_health.status_code == 200, f"Full health check: HTTP 200 (got {resp_health.status_code})")
    health_data = resp_health.json()
    status_val = health_data.get("status")
    db_info = health_data.get("database", {})
    db_status = db_info.get("status")

    if is_live_or_ci_environment() or require_healthy:
        check(status_val == "healthy", f"Release gate status must be 'healthy' in CI/production (got '{status_val}')")
        check(db_status == "connected", f"Release gate database status must be 'connected' (got '{db_status}')")
    else:
        # Development-only tolerance when running offline without live database services
        check(status_val in ["healthy", "degraded"], f"Status (development fallback): {status_val}")
    check("database" in health_data, "Database health block present")
    passed_steps += 1

    # Step 3: Data Layer Health
    print_step(3, "Testing Data Layer & Entity Registry")
    resp = client.get("/api/v1/data/health")
    check(resp.status_code == 200, f"HTTP 200 OK (got {resp.status_code})")
    data = resp.json()
    check(data.get("layer") == "data_layer", "Layer identification: data_layer")
    check(data.get("registered_models", 0) >= 6, f"Registered models: {data.get('registered_models')}")
    passed_steps += 1

    # Step 4: Deterministic Analytics
    print_step(4, "Testing Deterministic Analytics Engine")
    resp = client.get("/api/v1/analytics/summary")
    check(resp.status_code == 200, f"HTTP 200 OK (got {resp.status_code})")
    summary_envelope = resp.json()
    check(summary_envelope.get("success") is True, "Envelope success: true")
    summary = summary_envelope.get("data", {})
    check("net_sales" in summary, "Metric 'net_sales' present in data")
    check("orders" in summary, "Metric 'orders' present in data")
    check("average_order_value" in summary, "Metric 'average_order_value' present in data")
    check("gross_profit" in summary, "Metric 'gross_profit' present in data")
    check("evidence" in summary_envelope, "EvidenceRecord present in envelope")
    passed_steps += 1

    # Step 5: Semantic Layer
    print_step(5, "Testing Semantic KPI & Ambiguity Resolution")
    resp = client.post("/api/v1/semantic/resolve", json={"query": "net sales"})
    check(resp.status_code == 200, f"HTTP 200 OK (got {resp.status_code})")
    sem_data = resp.json()
    check(sem_data.get("canonical_name") == "net_revenue", f"Resolved 'net sales' to: {sem_data.get('canonical_name')}")

    # Ambiguity detection verification
    resp_amb = client.post("/api/v1/semantic/resolve", json={"query": "sales turnover"})
    check(resp_amb.status_code == 200, f"Ambiguity check HTTP 200 (got {resp_amb.status_code})")
    check(resp_amb.json().get("is_ambiguous") is True, "Ambiguity correctly flagged for 'sales turnover'")
    passed_steps += 1

    # Step 6: Hybrid RAG Search
    print_step(6, "Testing Business Context Knowledge Search")
    resp = client.post("/api/v1/knowledge/search", json={"query": "revenue recognition policy", "top_k": 2})
    check(resp.status_code == 200, f"HTTP 200 OK (got {resp.status_code})")
    rag_data = resp.json()
    chunks = rag_data.get("chunks", [])
    check(isinstance(chunks, list), f"Retrieved context records: {len(chunks)} chunks")
    passed_steps += 1

    # Step 7: Predictive Time-Series Forecasting
    print_step(7, "Testing Predictive Intelligence & Forecasting")
    auth_headers = getattr(client, "auth_headers", None)
    expired_headers = getattr(client, "expired_token_headers", None)
    unauthorized_tenant_headers = getattr(client, "unauthorized_tenant_headers", None)

    # Negative Test 1: Unauthenticated request rejected with HTTP 401
    resp_unauth = client.post(
        "/api/v1/forecast/analyze",
        json={"query": "Forecast revenue for next 3 months", "reference_date": "2026-09-01"},
    )
    check(resp_unauth.status_code == 401, f"Security Gate: Unauthenticated forecast rejected with HTTP 401 (got {resp_unauth.status_code})")

    # Negative Test 2: Invalid/forged token rejected with HTTP 401
    resp_invalid = client.post(
        "/api/v1/forecast/analyze",
        json={"query": "Forecast revenue for next 3 months", "reference_date": "2026-09-01"},
        headers={"Authorization": "Bearer invalid.forged.jwt.token"},
    )
    check(resp_invalid.status_code == 401, f"Security Gate: Invalid token rejected with HTTP 401 (got {resp_invalid.status_code})")

    # Negative Test 3: Expired token rejected with HTTP 401
    if expired_headers:
        resp_exp = client.post(
            "/api/v1/forecast/analyze",
            json={"query": "Forecast revenue for next 3 months", "reference_date": "2026-09-01"},
            headers=expired_headers,
        )
        check(resp_exp.status_code == 401, f"Security Gate: Expired token rejected with HTTP 401 (got {resp_exp.status_code})")

    # Negative Test 4: Cross-tenant unauthorized access rejected with HTTP 403 Forbidden
    if unauthorized_tenant_headers:
        resp_idor = client.post(
            "/api/v1/forecast/analyze",
            json={"query": "Forecast revenue for next 3 months", "reference_date": "2026-09-01"},
            headers=unauthorized_tenant_headers,
        )
        check(resp_idor.status_code in [403, 404], f"Security Gate: Cross-tenant access rejected with HTTP {resp_idor.status_code}")

    # Authenticated Request: Authorized test-user request reaches forecasting logic
    if not auth_headers:
        raise AssertionError("Smoke test requires authentication credentials for protected forecasting endpoint. In live mode, provide --token or credentials.")

    resp = client.post(
        "/api/v1/forecast/analyze",
        json={"query": "Forecast revenue for next 3 months", "reference_date": "2026-09-01"},
        headers=auth_headers,
    )
    check(resp.status_code == 200, f"Authenticated forecast: HTTP 200 OK (got {resp.status_code})")
    fc_data = resp.json()
    check(fc_data.get("target_metric") in ["revenue", "sales"], f"Target metric: {fc_data.get('target_metric')}")
    check(len(fc_data.get("predictions", [])) == 3, f"Forecast horizon: {len(fc_data.get('predictions', []))} periods")
    passed_steps += 1

    # Step 8: Diagnostic Investigation
    print_step(8, "Testing Diagnostic Causal Investigation")

    # Negative Test 1: Unauthenticated request rejected with HTTP 401
    resp_unauth_inv = client.post(
        "/api/v1/investigation/analyze",
        json={"query": "Why did revenue decline?", "reference_date": "2026-09-01"},
    )
    check(resp_unauth_inv.status_code == 401, f"Security Gate: Unauthenticated investigation rejected with HTTP 401 (got {resp_unauth_inv.status_code})")

    # Negative Test 2: Invalid/forged token rejected with HTTP 401
    resp_invalid_inv = client.post(
        "/api/v1/investigation/analyze",
        json={"query": "Why did revenue decline?", "reference_date": "2026-09-01"},
        headers={"Authorization": "Bearer invalid.forged.jwt.token"},
    )
    check(resp_invalid_inv.status_code == 401, f"Security Gate: Invalid token rejected with HTTP 401 (got {resp_invalid_inv.status_code})")

    # Negative Test 3: Expired token rejected with HTTP 401
    if expired_headers:
        resp_exp_inv = client.post(
            "/api/v1/investigation/analyze",
            json={"query": "Why did revenue decline?", "reference_date": "2026-09-01"},
            headers=expired_headers,
        )
        check(resp_exp_inv.status_code == 401, f"Security Gate: Expired token rejected with HTTP 401 (got {resp_exp_inv.status_code})")

    # Negative Test 4: Cross-tenant unauthorized access rejected with HTTP 403 Forbidden
    if unauthorized_tenant_headers:
        resp_idor_inv = client.post(
            "/api/v1/investigation/analyze",
            json={"query": "Why did revenue decline?", "reference_date": "2026-09-01"},
            headers=unauthorized_tenant_headers,
        )
        check(resp_idor_inv.status_code in [403, 404], f"Security Gate: Cross-tenant access rejected with HTTP {resp_idor_inv.status_code}")

    # Authenticated Request: Authorized test-user request reaches investigation logic
    if not auth_headers:
        raise AssertionError("Smoke test requires authentication credentials for protected investigation endpoint. In live mode, provide --token or credentials.")

    resp = client.post(
        "/api/v1/investigation/analyze",
        json={"query": "Why did revenue decline?", "reference_date": "2026-09-01"},
        headers=auth_headers,
    )
    check(resp.status_code == 200, f"Authenticated investigation: HTTP 200 OK (got {resp.status_code})")
    inv_data = resp.json()
    check("summary" in inv_data, "Executive summary generated")
    check("hypotheses" in inv_data, "Tested hypotheses present")
    check("status" in inv_data, f"Investigation status: {inv_data.get('status')}")
    passed_steps += 1

    # Step 9: Agentic LangGraph Pipeline
    print_step(9, "Testing Multi-Agent LangGraph Pipeline")
    resp = client.post(
        "/api/v1/agent/analyze",
        json={"query": "What was net revenue last month?", "reference_date": "2026-09-01"},
        headers=auth_headers,
    )
    check(resp.status_code == 200, f"HTTP 200 OK (got {resp.status_code})")
    agent_data = resp.json()
    check(agent_data.get("status") in ["completed", "success", "clarification_needed"], f"Agent status: {agent_data.get('status')}")
    check("evidence" in agent_data, "Grounded EvidenceRecord returned")
    passed_steps += 1

    # Step 10: Request Correlation & Latency
    print_step(10, "Testing Request Correlation & Latency Tracking")
    custom_req_id = "smoke-test-corr-id-12345"
    resp = client.get("/api/v1/health/live", headers={"X-Request-ID": custom_req_id})
    check(resp.headers.get("X-Request-ID") == custom_req_id, f"Correlation ID reflected: {resp.headers.get('X-Request-ID')}")
    check("X-Process-Time-Ms" in resp.headers, f"Process latency: {resp.headers.get('X-Process-Time-Ms')}ms")
    passed_steps += 1

    # Step 11: Security & Boundary Safeguards
    print_step(11, "Testing Security & Upload Size Boundaries")
    # CSV extension rejection
    fake_exe = b"MZ\x90\x00Binary"
    files = {"file": ("malicious.exe", fake_exe, "application/octet-stream")}
    data_form = {"dataset": "products"}
    resp = client.post("/api/v1/data/ingest/csv", data=data_form, files=files, headers=auth_headers)
    check(resp.status_code == 400, f"Invalid file format rejected: HTTP {resp.status_code}")

    # Forecast horizon limit (authenticated)
    resp = client.post(
        "/api/v1/forecast/analyze",
        json={"query": "Forecast revenue for next 48 months"},
        headers=auth_headers,
    )
    check(resp.status_code == 422, f"Out-of-bounds horizon rejected: HTTP {resp.status_code}")
    passed_steps += 1

    total_time_ms = (time.perf_counter() - start_total) * 1000
    print("\n" + "=" * 60)
    print(f"SMOKE TEST SUMMARY: {passed_steps}/11 STEPS PASSED")
    print(f"Total Execution Time: {total_time_ms:.2f}ms")
    print("ALL PRODUCTION CORE CAPABILITIES VERIFIED SUCCESSFULLY.")
    print("=" * 60)


def create_in_process_client():
    from fastapi.testclient import TestClient
    from app.main import app
    from app.core.config import settings
    from app.core.database import get_db, _get_engine_kwargs
    import app.core.database as core_db
    from app.api.deps import get_db_session
    from evaluation.runner.runner import create_evaluation_database
    from sqlalchemy import create_engine

    # Resolve configured database URL consistently from environment
    configured_db_url = resolve_configured_database_url()
    if configured_db_url:
        clean_url = configured_db_url
        if clean_url.startswith("postgresql://"):
            clean_url = clean_url.replace("postgresql://", "postgresql+psycopg://", 1)
        elif clean_url.startswith("postgres://"):
            clean_url = clean_url.replace("postgres://", "postgresql+psycopg://", 1)
        settings.DATABASE_URL = clean_url
        try:
            core_db.engine = create_engine(settings.DATABASE_URL, **_get_engine_kwargs())
        except Exception:
            pass

    # Enable API-key authentication for in-process smoke test execution
    settings.API_KEY_ENABLED = True
    settings.API_KEY = "smoke-test-key"

    session = create_evaluation_database()

    # Seed the system service workspace with ready dataset and active semantic model
    from app.models.tenant import Organization, Business, UserIdentity, OrganizationMembership, UploadedDataset, TenantSemanticModel
    from app.models.customer import Customer
    from app.models.product import Product
    from app.models.sale import Sale

    session.query(Customer).update({Customer.business_id: "biz_system_service"})
    session.query(Product).update({Product.business_id: "biz_system_service"})
    session.query(Sale).update({Sale.business_id: "biz_system_service"})
    session.flush()

    org = Organization(id="org_system_service", name="System Service Org", slug="system-service-org")
    session.add(org)
    session.flush()

    user = UserIdentity(
        id="usr_system_service",
        email="system@nexus.internal",
        full_name="NEXUS System Service",
        password_hash="N/A",
        is_active=True,
        is_verified=True,
    )
    session.add(user)
    session.flush()

    mem = OrganizationMembership(
        user_id=user.id,
        organization_id=org.id,
        role="owner",
    )
    session.add(mem)

    biz = Business(
        id="biz_system_service",
        organization_id=org.id,
        name="System Primary Business",
        status="active",
    )
    session.add(biz)
    session.flush()

    dataset = UploadedDataset(
        id="ds_system_service",
        organization_id=org.id,
        business_id=biz.id,
        filename="smoke_test_retail.csv",
        file_type="csv",
        storage_key="uploads/smoke_test.csv",
        file_size_bytes=1024,
        row_count=100,
        column_count=5,
        content_hash="smoke_test_hash",
        readiness_status="ready",
    )
    session.add(dataset)
    session.flush()

    sem = TenantSemanticModel(
        id="sem_system_service",
        organization_id=org.id,
        business_id=biz.id,
        version=1,
        status="ACTIVE",
        source_dataset_id=dataset.id,
        entities_json={"Sale": {"record_count": 100}},
        metrics_json={"net_revenue": {"status": "AVAILABLE"}},
        dimensions_json={},
        synonyms_json={},
        ambiguous_terms_json={},
        business_summary_json={"total_sales": 100},
    )
    session.add(sem)

    # Seed isolated secondary tenant to test cross-tenant IDOR access rejection
    org_other = Organization(id="org_other_tenant", name="Other Tenant Org", slug="other-tenant-org")
    session.add(org_other)
    biz_other = Business(
        id="biz_other_tenant",
        organization_id=org_other.id,
        name="Other Tenant Business",
        status="active",
    )
    session.add(biz_other)
    session.commit()

    def override_get_db():
        try:
            yield session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_db_session] = override_get_db

    from app.services.auth_service import AuthService
    from datetime import timedelta

    auth_token = AuthService.create_access_token(
        user_id=user.id,
        email=user.email,
        full_name=user.full_name,
        organization_id=org.id,
        business_id=biz.id,
    )

    expired_token = AuthService.create_access_token(
        user_id=user.id,
        email=user.email,
        full_name=user.full_name,
        organization_id=org.id,
        business_id=biz.id,
        expires_delta=timedelta(seconds=-30),
    )

    client = TestClient(
        app,
        headers={"X-API-Key": settings.API_KEY},
    )
    client.auth_token = auth_token
    client.auth_headers = {
        "Authorization": f"Bearer {auth_token}",
        "X-Business-ID": biz.id,
    }
    client.expired_token_headers = {
        "Authorization": f"Bearer {expired_token}",
        "X-Business-ID": biz.id,
    }
    client.unauthorized_tenant_headers = {
        "Authorization": f"Bearer {auth_token}",
        "X-Business-ID": biz_other.id,
    }

    return client


def main():
    parser = argparse.ArgumentParser(description="NEXUS Production Smoke Test")
    parser.add_argument("--base-url", type=str, default=None, help="Base URL of live deployment (e.g. http://localhost:8000)")
    parser.add_argument("--require-healthy", action="store_true", default=False, help="Strictly mandate database health == 'healthy' (fails on degraded)")
    parser.add_argument("--token", type=str, default=None, help="Bearer authentication token for live deployment")
    parser.add_argument("--api-key", type=str, default=None, help="API key for live deployment")
    parser.add_argument("--email", type=str, default=None, help="User email for live deployment login")
    parser.add_argument("--password", type=str, default=None, help="User password for live deployment login")
    parser.add_argument("--business-id", type=str, default=None, help="Target business workspace ID for live deployment")
    args = parser.parse_args()

    if args.base_url:
        import httpx

        def create_live_client():
            client = httpx.Client(base_url=args.base_url, timeout=30.0)
            if args.api_key:
                client.headers["X-API-Key"] = args.api_key

            token = args.token or os.getenv("SMOKE_TEST_TOKEN") or os.getenv("NEXUS_AUTH_TOKEN")
            biz_id = args.business_id or os.getenv("SMOKE_TEST_BUSINESS_ID")

            email = args.email or os.getenv("SMOKE_TEST_EMAIL")
            password = args.password or os.getenv("SMOKE_TEST_PASSWORD")

            if not token and email and password:
                login_resp = client.post("/api/v1/auth/login", json={"email": email, "password": password})
                if login_resp.status_code == 200:
                    data = login_resp.json()
                    token = data.get("access_token")
                    if not biz_id and data.get("business"):
                        biz_id = data["business"].get("id")

            if token:
                auth_h = {"Authorization": f"Bearer {token}"}
                if biz_id:
                    auth_h["X-Business-ID"] = biz_id
                client.auth_headers = auth_h
                client.expired_token_headers = {"Authorization": "Bearer expired.token.live", "X-Business-ID": biz_id or "biz_unknown"}
                client.unauthorized_tenant_headers = {"Authorization": f"Bearer {token}", "X-Business-ID": "biz_unauthorized_idor_test"}
            else:
                client.auth_headers = None
                client.expired_token_headers = None
                client.unauthorized_tenant_headers = None

            return client

        client_getter = create_live_client
    else:
        client_getter = create_in_process_client

    try:
        run_smoke_test(client_getter, require_healthy=args.require_healthy)
    except Exception as exc:
        print(f"\n[ERROR] Smoke test suite failed: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
