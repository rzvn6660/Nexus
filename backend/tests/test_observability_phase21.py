"""Phase 21 - Production Observability & Reliability Tests.

Covers:
1. AnalysisRun persist failure escalates to logger.error (not silently discarded)
2. IDOR attempt is logged as SECURITY warning in verify_user_business_access
3. Failed login attempt is logged as SECURITY warning
4. Data gateway: executable upload rejection is logged as SECURITY warning
5. Data gateway: shell script upload rejection is logged as SECURITY warning
6. Data gateway: prohibited extension rejection is logged as SECURITY warning
7. Health endpoint returns 'degraded' when DB is down
8. Readiness probe returns HTTP 503 when DB is down
9. Health endpoint returns 'healthy' when DB is up
10. Ingestion lifecycle logs STARTED and COMPLETED
11. Ingestion FAILED path logs at error level
"""

import csv as csv_mod
import io
import os
import tempfile
from unittest.mock import patch, MagicMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.main import app


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="function")
def client(db_session):
    """TestClient with in-memory DB override."""
    from app.core.database import get_db

    def _override():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = _override
    yield TestClient(app, raise_server_exceptions=False)
    app.dependency_overrides.clear()


def _make_org_biz(db, org_id: str, biz_id: str, user_id: str):
    from app.models.tenant import Organization, OrganizationMembership, Business
    org = Organization(id=org_id, name="Org", slug=f"org-{org_id[:6]}", status="active")
    db.add(org)
    db.flush()
    mem = OrganizationMembership(organization_id=org_id, user_id=user_id, role="owner")
    db.add(mem)
    biz = Business(
        id=biz_id, organization_id=org_id, name="Biz", industry="Retail",
        country="US", currency="USD", timezone="UTC", business_type="B2C",
        fiscal_year_start=1, status="active", onboarding_step="completed",
        data_readiness_status="READY",
    )
    db.add(biz)
    db.flush()
    return org, biz


# ---------------------------------------------------------------------------
# 1. _persist_run failure escalates to logger.error
# ---------------------------------------------------------------------------

def test_persist_run_failure_logs_at_error_level(db_session):
    from app.agents.service import NexusAgentService
    service = NexusAgentService(db_session)
    with patch.object(db_session, "add", side_effect=RuntimeError("mock-db-crash")):
        with patch("app.agents.service.logger") as mock_logger:
            service._persist_run(
                request_id="req-obs-001",
                organization_id="org-1",
                business_id="biz-1",
                user_id="user-1",
                query="test query",
                intent="analytical",
                run_status="completed",
                explanation_level="manager",
                answer="Test.",
                elapsed_ms=10.0,
                tools_used=[],
                calculations=[],
                assumptions=[],
                limitations=[],
                evidence_records=[],
                rag_citations=[],
                snapshot={},
                recommendations=[],
            )
            mock_logger.error.assert_called_once()
            call_msg = mock_logger.error.call_args[0][0]
            assert "req-obs-001" in call_msg
            assert "Failed to persist" in call_msg


# ---------------------------------------------------------------------------
# 2. IDOR attempt triggers SECURITY warning log
# ---------------------------------------------------------------------------

def test_idor_attempt_logs_security_warning(db_session):
    from app.core.auth import verify_user_business_access
    from app.models.tenant import UserIdentity, Organization, OrganizationMembership, Business
    from app.services.auth_service import AuthService
    from fastapi import HTTPException

    user = UserIdentity(
        id="idor-alice", email="alice@obs.invalid",
        password_hash=AuthService.hash_password("Pass1234!"),
        full_name="Alice", is_active=True, is_verified=True,
    )
    db_session.add(user)
    org_a = Organization(id="org-idor-a", name="A", slug="org-a", status="active")
    db_session.add(org_a)
    db_session.flush()
    db_session.add(OrganizationMembership(organization_id="org-idor-a", user_id="idor-alice", role="owner"))
    org_b = Organization(id="org-idor-b", name="B", slug="org-b", status="active")
    db_session.add(org_b)
    db_session.flush()
    other_biz = Business(
        id="biz-idor-other", organization_id="org-idor-b", name="Other",
        industry="Tech", country="US", currency="USD", timezone="UTC",
        business_type="B2B", fiscal_year_start=1, status="active",
        onboarding_step="completed", data_readiness_status="READY",
    )
    db_session.add(other_biz)
    db_session.flush()

    with patch("app.core.auth.logger") as mock_logger:
        with pytest.raises(HTTPException) as exc:
            verify_user_business_access(db_session, user, "biz-idor-other", action="view data of")
        assert exc.value.status_code == 403
        mock_logger.warning.assert_called_once()
        call_msg = mock_logger.warning.call_args[0][0]
        assert "IDOR" in call_msg or "SECURITY" in call_msg


# ---------------------------------------------------------------------------
# 3. Failed login logs SECURITY warning (without logging the password)
# ---------------------------------------------------------------------------

def test_failed_login_logs_security_warning(db_session, client):
    from app.services.auth_service import AuthService
    from app.models.tenant import UserIdentity
    user = UserIdentity(
        id="bob-obs", email="bob@obs.invalid",
        password_hash=AuthService.hash_password("Correct1!"),
        full_name="Bob", is_active=True, is_verified=True,
    )
    db_session.add(user)
    db_session.commit()

    with patch("app.services.auth_service.logger") as mock_logger:
        resp = client.post("/api/v1/auth/login",
                           json={"email": "bob@obs.invalid", "password": "WrongPass1!"})
        assert resp.status_code == 401
        mock_logger.warning.assert_called_once()
        logged = str(mock_logger.warning.call_args)
        assert "bob@obs.invalid" in logged
        assert "SECURITY" in logged
        # Password must NOT appear in any log
        assert "WrongPass1" not in logged


# ---------------------------------------------------------------------------
# 4. Executable binary upload - SECURITY warning logged
# ---------------------------------------------------------------------------

def test_executable_upload_rejected_and_logged():
    exe_content = b"MZ\x90\x00" + b"\x00" * 100
    with patch("app.services.data_gateway_service.logger") as mock_logger:
        with pytest.raises(Exception):
            from app.services.data_gateway_service import DataGatewayService
            DataGatewayService.validate_file_security("data.csv", exe_content)
        mock_logger.warning.assert_called_once()
        logged = str(mock_logger.warning.call_args)
        assert "SECURITY" in logged


# ---------------------------------------------------------------------------
# 5. Shell script upload - SECURITY warning logged
# ---------------------------------------------------------------------------

def test_shell_script_upload_rejected_and_logged():
    script = b"#!/bin/bash\nrm -rf /\n"
    with patch("app.services.data_gateway_service.logger") as mock_logger:
        with pytest.raises(Exception):
            from app.services.data_gateway_service import DataGatewayService
            DataGatewayService.validate_file_security("data.csv", script)
        mock_logger.warning.assert_called_once()
        logged = str(mock_logger.warning.call_args)
        assert "SECURITY" in logged


# ---------------------------------------------------------------------------
# 6. Prohibited extension upload - SECURITY warning logged
# ---------------------------------------------------------------------------

def test_prohibited_extension_rejected_and_logged():
    content = b"some binary payload"
    with patch("app.services.data_gateway_service.logger") as mock_logger:
        with pytest.raises(Exception):
            from app.services.data_gateway_service import DataGatewayService
            DataGatewayService.validate_file_security("payload.exe", content)
        mock_logger.warning.assert_called_once()
        logged = str(mock_logger.warning.call_args)
        assert "SECURITY" in logged


# ---------------------------------------------------------------------------
# 7-9. Health endpoint accuracy
# ---------------------------------------------------------------------------

def test_health_degraded_when_db_down():
    with patch("app.api.v1.endpoints.health.check_database_connection",
               return_value={"status": "disconnected", "error": "Connection refused"}):
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/api/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "degraded"
        assert body["dependency_status"] == "degraded"


def test_health_healthy_when_db_up():
    with patch("app.api.v1.endpoints.health.check_database_connection",
               return_value={"status": "connected", "latency_ms": 0.8}):
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/api/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "healthy"
        assert body["dependency_status"] == "optimal"


def test_readiness_probe_503_when_db_down():
    with patch("app.api.v1.endpoints.health.check_database_connection",
               return_value={"status": "disconnected", "error": "Timeout"}):
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/api/health/ready")
        assert resp.status_code == 503
        assert resp.json()["status"] == "not_ready"


# ---------------------------------------------------------------------------
# 10. Ingestion lifecycle logs STARTED and COMPLETED
# ---------------------------------------------------------------------------

def test_ingestion_lifecycle_logs_started_and_completed(db_session):
    from app.services.data_gateway_service import DataGatewayService
    from app.models.tenant import UploadedDataset, Organization, Business

    rows = [
        ["transaction_date", "amount", "order_id"],
        ["2024-01-01", "100.00", "TXN-OBS-001"],
        ["2024-01-02", "200.00", "TXN-OBS-002"],
    ]
    buf = io.StringIO()
    csv_mod.writer(buf).writerows(rows)
    csv_bytes = buf.getvalue().encode("utf-8")

    org_id = str(uuid4())
    biz_id = str(uuid4())
    dataset_id = str(uuid4())

    org = Organization(id=org_id, name="LCOrg", slug=f"lc-{org_id[:4]}", status="active")
    db_session.add(org)
    biz = Business(
        id=biz_id, organization_id=org_id, name="LCBiz", industry="Retail",
        country="US", currency="USD", timezone="UTC", business_type="B2C",
        fiscal_year_start=1, status="active", onboarding_step="completed",
        data_readiness_status="READY",
    )
    db_session.add(biz)
    db_session.flush()

    tmp = tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="wb")
    tmp.write(csv_bytes)
    tmp.close()

    schema_json = {
        "mapping_proposal": {
            "target_entity": "Sale",
            "field_mappings": {
                "transaction_date": "date",
                "amount": "amount",
                "order_id": "order_number",
            },
            "missing_required_fields": [],
        },
        "ingestion_status": "PENDING",
    }
    ds = UploadedDataset(
        id=dataset_id, organization_id=org_id, business_id=biz_id,
        filename="sales.csv", file_type="csv",
        storage_key=tmp.name.replace("\\", "/"),
        file_size_bytes=len(csv_bytes), row_count=2, column_count=3,
        content_hash="obs-hash-001",
        schema_json=schema_json,
        quality_report_json={"readiness_score": 90},
        readiness_status="READY",
    )
    db_session.add(ds)
    db_session.flush()

    try:
        with patch("app.services.data_gateway_service.logger") as mock_logger:
            result = DataGatewayService.ingest_into_core_models(
                db=db_session, dataset_id=dataset_id,
                business_id=biz_id, target_entity="Sale",
            )
            assert result["status"] == "COMPLETED"
            info_calls = [str(c) for c in mock_logger.info.call_args_list]
            assert any("started" in c.lower() for c in info_calls), "Missing 'started' log"
            assert any("completed" in c.lower() for c in info_calls), "Missing 'completed' log"
    finally:
        os.unlink(tmp.name)


# ---------------------------------------------------------------------------
# 11. Ingestion FAILED exception logs at error level
# ---------------------------------------------------------------------------

def test_ingestion_exception_logs_at_error_level(db_session):
    """An unexpected exception during ingestion body must log at error level."""
    from app.services.data_gateway_service import DataGatewayService
    from app.models.tenant import UploadedDataset, Organization, Business
    from fastapi import HTTPException
    import pandas as pd

    org_id = str(uuid4())
    biz_id = str(uuid4())
    dataset_id = str(uuid4())

    org = Organization(id=org_id, name="ErrOrg", slug=f"eo-{org_id[:4]}", status="active")
    db_session.add(org)
    biz = Business(
        id=biz_id, organization_id=org_id, name="ErrBiz", industry="Retail",
        country="US", currency="USD", timezone="UTC", business_type="B2C",
        fiscal_year_start=1, status="active", onboarding_step="completed",
        data_readiness_status="READY",
    )
    db_session.add(biz)
    db_session.flush()

    # Create a real temp file so the "file not found" check passes
    tmp = tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="wb")
    tmp.write(b"transaction_date,amount\n2024-01-01,100\n")
    tmp.close()

    schema_json = {
        "mapping_proposal": {
            "target_entity": "Sale",
            "field_mappings": {"amount": "amount"},
            "missing_required_fields": [],
        },
        "ingestion_status": "PENDING",
    }
    ds = UploadedDataset(
        id=dataset_id, organization_id=org_id, business_id=biz_id,
        filename="crash.csv", file_type="csv",
        storage_key=tmp.name.replace("\\", "/"),
        file_size_bytes=100, row_count=2, column_count=2,
        content_hash="dead0000",
        schema_json=schema_json,
        quality_report_json={"readiness_score": 80},
        readiness_status="READY",
    )
    db_session.add(ds)
    db_session.flush()

    try:
        # Patch pd.read_csv to simulate an unexpected crash after the file is opened
        with patch("app.services.data_gateway_service.pd.read_csv",
                   side_effect=RuntimeError("simulated-pandas-crash")):
            with patch("app.services.data_gateway_service.logger") as mock_logger:
                with pytest.raises(HTTPException) as exc:
                    DataGatewayService.ingest_into_core_models(
                        db=db_session, dataset_id=dataset_id,
                        business_id=biz_id, target_entity="Sale",
                    )
                assert exc.value.status_code == 500
                mock_logger.error.assert_called_once()
                err_msg = str(mock_logger.error.call_args)
                assert "FAILED" in err_msg
    finally:
        os.unlink(tmp.name)


# ---------------------------------------------------------------------------
# 12. Correlation ID ContextVar propagation to nested service logs
# ---------------------------------------------------------------------------

def test_correlation_id_contextvar_propagated_to_service_logs(client):
    """Verify incoming X-Request-ID is set in ContextVar and captured by CorrelationFilter."""
    import logging
    from app.core.logging import get_logger, correlation_id_var

    test_logger = get_logger("nexus.test_service")
    custom_id = "req-trace-abc-123"

    # Capture log records emitted during request
    records = []
    class ListHandler(logging.Handler):
        def emit(self, record):
            records.append(record)

    handler = ListHandler()
    logging.getLogger().addHandler(handler)

    try:
        # Before request, ContextVar is default "-"
        assert correlation_id_var.get() == "-"

        # Invoke health endpoint with custom X-Request-ID
        resp = client.get("/api/health", headers={"X-Request-ID": custom_id})
        assert resp.status_code == 200
        assert resp.headers["X-Request-ID"] == custom_id

        # At least one log record should have been created with our correlation_id
        matched = [r for r in records if getattr(r, "correlation_id", None) == custom_id]
        assert len(matched) > 0, f"Expected log records with correlation_id={custom_id}"

        # After request completes, ContextVar must be reset back to "-"
        assert correlation_id_var.get() == "-"
    finally:
        logging.getLogger().removeHandler(handler)


# ---------------------------------------------------------------------------
# 13. Auto-generated Correlation ID propagation and ContextVar reset
# ---------------------------------------------------------------------------

def test_generated_correlation_id_propagates_and_resets(client):
    """When no X-Request-ID header is provided, generated UUID is propagated and reset."""
    import logging
    from app.core.logging import correlation_id_var

    records = []
    class ListHandler(logging.Handler):
        def emit(self, record):
            records.append(record)

    handler = ListHandler()
    logging.getLogger().addHandler(handler)

    try:
        assert correlation_id_var.get() == "-"
        resp = client.get("/api/health")
        assert resp.status_code == 200
        gen_id = resp.headers.get("X-Request-ID")
        assert gen_id is not None and len(gen_id) > 10

        matched = [r for r in records if getattr(r, "correlation_id", None) == gen_id]
        assert len(matched) > 0, f"Expected log records with correlation_id={gen_id}"
        assert correlation_id_var.get() == "-"
    finally:
        logging.getLogger().removeHandler(handler)


# ---------------------------------------------------------------------------
# 14. AuthService failed authentication security warning for nonexistent user
# ---------------------------------------------------------------------------

def test_auth_service_failed_auth_nonexistent_user_logged(db_session):
    """AuthService.authenticate logs SECURITY warning for nonexistent user without leaking info."""
    from app.services.auth_service import AuthService

    with patch("app.services.auth_service.logger") as mock_logger:
        res = AuthService.authenticate(db=db_session, email="ghost@nexus.invalid", password="SomePassword123!")
        assert res is None
        mock_logger.warning.assert_called_once()
        log_str = str(mock_logger.warning.call_args)
        assert "ghost@nexus.invalid" in log_str
        assert "SECURITY" in log_str
        assert "SomePassword123!" not in log_str

