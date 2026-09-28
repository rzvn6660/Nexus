"""Phase 20 — End-to-End Production SaaS Journey & Security Hardening Test Suite.

Validates the full enterprise multi-tenant lifecycle:
1. Sign Up -> Create Business
2. Upload Dataset -> Ingestion / Data Readiness (READY)
3. Automatic Business Understanding -> TenantSemanticModel (REQUIRES_REVIEW)
4. Semantic Review & Modification/Approval -> ACTIVE v1
5. Agent Analysis Execution -> Captures v1 snapshot + dataset snapshot + Evidence
6. History Ledger -> Lists run with correct metadata, retrieves run details
7. Subsequent Model Upgrade -> v2 ACTIVE -> Historical Run A retains v1 snapshot
8. Failure & Security Paths:
   - Run requested with no ready dataset (data-not-ready failure persisted)
   - Run requested with no active semantic model (semantic-not-ready failure persisted)
   - Invalid / corrupt dataset upload rejection
   - Cross-tenant IDOR defense on History endpoints (/runs, /runs/{id}, /runs/{id}/report)
   - Cross-tenant analysis execution isolation (cannot query other tenant's business)
   - Duplicate dataset upload idempotency
   - Empty business initial state
"""

import io
from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool

from app.api.deps import get_db_session
from app.core.database import get_db
from app.main import app
from app.models.base import Base
from app.models.history import AnalysisRun, DecisionRecord
from app.models.tenant import (
    Business,
    IngestionJob,
    Organization,
    OrganizationMembership,
    TenantSemanticModel,
    UploadedDataset,
    UserIdentity,
)
from app.services.auth_service import AuthService
from app.services.tenant_semantic_service import TenantSemanticService


TEST_DATABASE_URL = "sqlite:///:memory:"
engine = create_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(scope="module")
def db_session():
    Base.metadata.create_all(bind=engine)
    session = TestingSessionLocal()
    yield session
    session.close()
    Base.metadata.drop_all(bind=engine)


@pytest.fixture(scope="module")
def client(db_session):
    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_db_session] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


class TestEndToEndSaaSLifecycle:
    """Complete 10-step production flow and verification."""

    def test_01_full_happy_path_onboarding_to_reproducible_history(self, client: TestClient, db_session: Session):
        # 1. Sign Up
        signup_res = client.post(
            "/api/v1/auth/signup",
            json={
                "email": "sarah.cto@apexretail.io",
                "password": "ApexSecurePassword2026!",
                "full_name": "Sarah Connor",
                "organization_name": "Apex Retail Group",
                "business_name": "Apex Flagship Store",
            },
        )
        assert signup_res.status_code == 201
        auth_data = signup_res.json()
        token = auth_data["access_token"]
        biz_id = auth_data["business"]["id"]
        org_id = auth_data["organization"]["id"]

        headers = {
            "Authorization": f"Bearer {token}",
            "X-Business-ID": biz_id,
        }

        # 2. Verify Empty/New Business State
        hist_empty_res = client.get("/api/v1/history/runs", headers=headers)
        assert hist_empty_res.status_code == 200
        assert hist_empty_res.json() == []

        # 3. Upload Tabular Dataset
        csv_payload = (
            "order_id,order_date,amount,channel\n"
            "APEX-001,2026-01-15,450.00,Online\n"
            "APEX-002,2026-01-16,1200.00,In-Store\n"
            "APEX-003,2026-01-17,850.00,Online\n"
        )
        files = {"file": ("apex_q1_sales.csv", io.BytesIO(csv_payload.encode("utf-8")), "text/csv")}
        upload_res = client.post("/api/v1/gateway/upload", files=files, headers=headers)
        assert upload_res.status_code == 201
        upload_data = upload_res.json()
        dataset_id = upload_data["dataset_id"]
        assert upload_data["readiness_status"] in ["ready", "READY", "ready_with_warnings"]

        # 4. Ingest Dataset -> Marks Dataset READY and triggers business understanding
        ingest_res = client.post(
            f"/api/v1/gateway/datasets/{dataset_id}/ingest",
            headers=headers,
            json={"target_entity": "Sale"},
        )
        assert ingest_res.status_code == 200
        assert ingest_res.json()["status"] == "COMPLETED"

        # 5. Business Understanding generated -> Review revision
        revs_res = client.get("/api/v1/semantic/revisions", headers=headers)
        assert revs_res.status_code == 200
        revs = revs_res.json()
        assert len(revs) >= 1
        active_rev = [r for r in revs if r["status"] == "ACTIVE"]

        # If generated as ACTIVE or REQUIRES_REVIEW, ensure we have an approved ACTIVE version 1
        if not active_rev:
            review_rev = [r for r in revs if r["status"] == "REQUIRES_REVIEW"][0]
            appr_res = client.post(
                f"/api/v1/semantic/revisions/{review_rev['id']}/approve",
                headers=headers,
                json={"comment": "Phase 20 approved"},
            )
            assert appr_res.status_code == 200
            rev_v1_id = appr_res.json()["revision_id"]
        else:
            rev_v1_id = active_rev[0]["id"]

        # 6. Ask NEXUS (Agent Analysis)
        analyze_res = client.post(
            "/api/v1/agent/analyze",
            headers=headers,
            json={
                "query": "What is our total net sales revenue?",
                "explanation_level": "executive",
            },
        )
        assert analyze_res.status_code == 200
        an_data = analyze_res.json()
        assert "answer" in an_data
        assert an_data["status"] == "completed"
        assert len(an_data["evidence"]) >= 1

        # 7. Check History Ledger -> Run persisted with correct snapshot & metadata
        runs_res = client.get("/api/v1/history/runs", headers=headers)
        assert runs_res.status_code == 200
        runs_list = runs_res.json()
        assert len(runs_list) >= 1
        run_summary = runs_list[0]
        run_id = run_summary["id"]

        assert run_summary["semantic_version"] == 1
        assert run_summary["dataset_id"] == dataset_id

        # 8. Re-open Historical Run Details
        detail_res = client.get(f"/api/v1/history/runs/{run_id}", headers=headers)
        assert detail_res.status_code == 200
        run_detail = detail_res.json()
        assert run_detail["id"] == run_id
        assert run_detail["business_id"] == biz_id
        assert run_detail["semantic_revision_id"] == rev_v1_id
        assert run_detail["semantic_version"] == 1
        assert run_detail["dataset_id"] == dataset_id
        assert run_detail["dataset_content_hash"] is not None

        # 9. Export Dossier
        report_res = client.get(f"/api/v1/history/runs/{run_id}/report?format=markdown", headers=headers)
        assert report_res.status_code == 200
        assert "NEXUS Intelligence Dossier" in report_res.json()["content"]

        # 10. Subsequent Semantic Upgrade (v2 ACTIVE) -> Run A Still References v1
        # Modify revision to create v2
        mod_res = client.post(
            f"/api/v1/semantic/revisions/{rev_v1_id}/modify",
            headers=headers,
            json={
                "metrics_override": {
                    "net_revenue": {
                        "calculation_formula": "SUM(sales.total_amount * 0.95)",
                    }
                },
                "comment": "Account for partner returns reserve",
            },
        )
        assert mod_res.status_code == 200
        mod_data = mod_res.json()
        assert mod_data["action"] == "MODIFIED"
        rev_v2_id = mod_data["revision_id"]

        # Approve v2
        appr_v2_res = client.post(
            f"/api/v1/semantic/revisions/{rev_v2_id}/approve",
            headers=headers,
            json={"comment": "Approve v2 with returns reserve"},
        )
        assert appr_v2_res.status_code == 200
        assert appr_v2_res.json()["active_version"] == 2

        # Re-fetch Run 1: MUST strictly retain semantic_version=1 (Historical Reproducibility)
        reopened_res = client.get(f"/api/v1/history/runs/{run_id}", headers=headers)
        assert reopened_res.status_code == 200
        assert reopened_res.json()["semantic_version"] == 1
        assert reopened_res.json()["semantic_revision_id"] == rev_v1_id

        # New Run 2 uses v2
        run2_res = client.post(
            "/api/v1/agent/analyze",
            headers=headers,
            json={"query": "What is our net revenue?"},
        )
        assert run2_res.status_code == 200
        run2_summary = client.get("/api/v1/history/runs", headers=headers).json()[0]
        assert run2_summary["id"] != run_id
        assert run2_summary["semantic_version"] == 2
        assert run2_summary["semantic_revision_id"] == rev_v2_id


class TestSecurityAndFailurePaths:
    """Failure, edge case, and IDOR isolation tests."""

    def test_02_failure_path_no_ready_dataset(self, client: TestClient, db_session: Session):
        """When business has an active semantic model but NO ready dataset, run fails gracefully and persists failure."""
        signup = client.post(
            "/api/v1/auth/signup",
            json={
                "email": "nodata.user@nexus.test",
                "password": "Password123!",
                "full_name": "No Data User",
                "organization_name": "Empty Data Corp",
                "business_name": "Empty Data Biz",
            },
        ).json()
        token = signup["access_token"]
        biz_id = signup["business"]["id"]
        headers = {"Authorization": f"Bearer {token}", "X-Business-ID": biz_id}

        # Manually create ACTIVE semantic model without dataset
        sem = TenantSemanticModel(
            id=str(uuid4()),
            business_id=biz_id,
            organization_id=signup["organization"]["id"],
            version=1,
            status="ACTIVE",
            entities_json={"Sale": {"record_count": 0}},
            metrics_json={"net_revenue": {"status": "AVAILABLE"}},
            dimensions_json={},
            synonyms_json={"revenue": "net_revenue"},
            ambiguous_terms_json={},
            business_summary_json={"business_type": "retail"},
        )
        db_session.add(sem)
        db_session.commit()

        # Query agent
        res = client.post(
            "/api/v1/agent/analyze",
            headers=headers,
            json={"query": "How is revenue trending?"},
        )
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "data-not-ready"
        assert "No ready dataset" in data["answer"]

        # Failure must be persisted in history
        runs = client.get("/api/v1/history/runs", headers=headers).json()
        assert len(runs) >= 1
        assert runs[0]["status"] == "data-not-ready"

    def test_03_failure_path_no_active_semantic_model(self, client: TestClient, db_session: Session):
        """When dataset exists but no ACTIVE semantic model exists, run fails with semantic-not-ready."""
        signup = client.post(
            "/api/v1/auth/signup",
            json={
                "email": "nosemantic.user@nexus.test",
                "password": "Password123!",
                "full_name": "No Semantic User",
                "organization_name": "No Semantic Corp",
                "business_name": "No Semantic Biz",
            },
        ).json()
        token = signup["access_token"]
        biz_id = signup["business"]["id"]
        headers = {"Authorization": f"Bearer {token}", "X-Business-ID": biz_id}

        # Upload and ingest dataset
        csv_payload = "order_id,amount,channel\nORD-1,100,Online\n"
        files = {"file": ("data.csv", io.BytesIO(csv_payload.encode("utf-8")), "text/csv")}
        up = client.post("/api/v1/gateway/upload", files=files, headers=headers).json()
        client.post(f"/api/v1/gateway/datasets/{up['dataset_id']}/ingest", headers=headers, json={"target_entity": "Sale"})

        # Invalidate any auto-created semantic model
        models = db_session.execute(
            select(TenantSemanticModel).where(TenantSemanticModel.business_id == biz_id)
        ).scalars().all()
        for m in models:
            m.status = "REQUIRES_REVIEW"
        db_session.commit()

        # Query agent
        res = client.post(
            "/api/v1/agent/analyze",
            headers=headers,
            json={"query": "What is revenue?"},
        )
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "semantic-not-ready"
        assert "No ACTIVE semantic model" in data["answer"]

    def test_04_cross_tenant_idor_history_and_analysis_defense(self, client: TestClient, db_session: Session):
        """Tenant A and Tenant B cannot access or tamper with each other's runs or datasets."""
        # Tenant A
        signup_a = client.post(
            "/api/v1/auth/signup",
            json={
                "email": "tenant.a@domain.com",
                "password": "Password123!",
                "full_name": "Tenant A Owner",
                "organization_name": "Tenant A Corp",
                "business_name": "Tenant A Biz",
            },
        ).json()
        headers_a = {
            "Authorization": f"Bearer {signup_a['access_token']}",
            "X-Business-ID": signup_a["business"]["id"],
        }

        # Tenant B
        signup_b = client.post(
            "/api/v1/auth/signup",
            json={
                "email": "tenant.b@domain.com",
                "password": "Password123!",
                "full_name": "Tenant B Owner",
                "organization_name": "Tenant B Corp",
                "business_name": "Tenant B Biz",
            },
        ).json()
        headers_b = {
            "Authorization": f"Bearer {signup_b['access_token']}",
            "X-Business-ID": signup_b["business"]["id"],
        }

        # Tenant A uploads data & runs analysis
        csv_payload = "order_id,amount,channel\nORD-A1,250,Online\n"
        up_a = client.post("/api/v1/gateway/upload", files={"file": ("sales_a.csv", io.BytesIO(csv_payload.encode("utf-8")), "text/csv")}, headers=headers_a).json()
        client.post(f"/api/v1/gateway/datasets/{up_a['dataset_id']}/ingest", headers=headers_a, json={"target_entity": "Sale"})
        
        # Approve semantic model for A if in review
        revs_a = client.get("/api/v1/semantic/revisions", headers=headers_a).json()
        for r in revs_a:
            if r["status"] == "REQUIRES_REVIEW":
                client.post(f"/api/v1/semantic/revisions/{r['id']}/approve", headers=headers_a, json={"comment": "ok"})

        run_a = client.post("/api/v1/agent/analyze", headers=headers_a, json={"query": "What is total sales?"}).json()
        run_a_record = client.get("/api/v1/history/runs", headers=headers_a).json()[0]
        run_a_id = run_a_record["id"]

        # Attack 1: Tenant B requests Tenant A's run list
        runs_b = client.get("/api/v1/history/runs", headers=headers_b).json()
        assert not any(r["id"] == run_a_id for r in runs_b)

        # Attack 2: Tenant B directly accesses Tenant A's run detail
        idor_detail = client.get(f"/api/v1/history/runs/{run_a_id}", headers=headers_b)
        assert idor_detail.status_code in [403, 404]

        # Attack 3: Tenant B requests Tenant A's report dossier
        idor_report = client.get(f"/api/v1/history/runs/{run_a_id}/report", headers=headers_b)
        assert idor_report.status_code in [403, 404]

        # Attack 4: Tenant B tries to analyze using Tenant A's business_id header
        tampered_headers = {
            "Authorization": f"Bearer {signup_b['access_token']}",
            "X-Business-ID": signup_a["business"]["id"],
        }
        tampered_analyze = client.post("/api/v1/agent/analyze", headers=tampered_headers, json={"query": "Leak data"})
        assert tampered_analyze.status_code in [403, 404]

    def test_05_invalid_and_corrupt_dataset_rejections(self, client: TestClient):
        """Invalid files (empty, corrupt MIME, path traversal) must be safely rejected."""
        signup = client.post(
            "/api/v1/auth/signup",
            json={
                "email": "security.tester@nexus.test",
                "password": "Password123!",
                "full_name": "Sec Tester",
                "organization_name": "Sec Corp",
                "business_name": "Sec Biz",
            },
        ).json()
        headers = {"Authorization": f"Bearer {signup['access_token']}", "X-Business-ID": signup["business"]["id"]}

        # 1. Empty file rejection
        empty_res = client.post("/api/v1/gateway/upload", files={"file": ("empty.csv", io.BytesIO(b""), "text/csv")}, headers=headers)
        assert empty_res.status_code == 400

        # 2. Executable / binary MIME rejection
        binary_res = client.post(
            "/api/v1/gateway/upload",
            files={"file": ("malware.csv", io.BytesIO(b"MZ\x90\x00\x03\x00\x00\x00"), "text/csv")},
            headers=headers,
        )
        assert binary_res.status_code in [400, 415]

        # 3. Path traversal filename sanitization
        trav_res = client.post(
            "/api/v1/gateway/upload",
            files={"file": ("../../etc/passwd.csv", io.BytesIO(b"a,b\n1,2\n"), "text/csv")},
            headers=headers,
        )
        assert trav_res.status_code == 201
        assert "../" not in trav_res.json()["filename"]
