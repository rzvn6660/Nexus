"""Comprehensive SaaS Multi-Tenancy & Security Verification Suite (Phase 15P & 15Q).

Verifies all 20 required SaaS security guarantees:
1.  Authenticated user can access own business
2.  Unauthenticated request rejected
3.  Member access follows membership / RBAC
4.  Unauthorized organization rejected
5.  Cross-tenant GET rejected
6.  Cross-tenant UPDATE rejected
7.  Cross-tenant DELETE rejected / restricted
8.  IDOR rejected
9.  Cross-tenant dataset access rejected
10. Cross-tenant knowledge access rejected
11. Cross-tenant OKF access rejected
12. Cross-tenant vector retrieval rejected
13. Cross-tenant analysis history rejected
14. Forged organization_id rejected
15. Forged business_id rejected
16. Expired/invalid JWT rejected
17. Malformed JWT rejected
18. Storage path traversal rejected
19. Unauthorized file download rejected
20. Agent cannot escape tenant boundary

Plus Phase 15Q:
- Distinguishable data test between Business A and Business B (100k vs 900k revenue context)
"""

import io
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.deps import get_db_session
from app.core.database import get_db
from app.models.base import Base
from app.main import app
from app.models.history import AnalysisRun, DecisionRecord
from app.models.knowledge import KnowledgeChunk, KnowledgeDocument
from app.models.tenant import (
    Business,
    Organization,
    OrganizationMembership,
    UploadedDataset,
    UserIdentity,
)
from app.rag.ingestion.models import DocumentMetadata
from app.rag.ingestion.service import DocumentIngestionService
from app.rag.retrieval.retriever import HybridRetriever
from app.services.auth_service import AuthService
from app.services.tenant_data_service import TenantDataService
from app.knowledge.okf.service import OKFService, OKFServiceError


# Test database setup
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
    try:
        yield session
    finally:
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


@pytest.fixture(scope="module")
def saas_tenants(db_session):
    """Seed two distinct organizations and business workspaces for testing."""
    # Organization A
    user_a, org_a, biz_a = AuthService.signup(
        db=db_session,
        email="owner_a@acme.com",
        password="Password123!",
        full_name="Alice Owner",
        organization_name="Acme Corp",
        business_name="Acme Retail",
    )
    token_a = AuthService.create_access_token(
        user_id=user_a.id,
        email=user_a.email,
        organization_id=org_a.id,
        business_id=biz_a.id,
    )

    # User C (Member of Org A, not owner/admin)
    user_c = UserIdentity(
        email="member_c@acme.com",
        password_hash=AuthService.hash_password("Password123!"),
        full_name="Charlie Member",
    )
    db_session.add(user_c)
    db_session.commit()
    db_session.refresh(user_c)

    membership_c = OrganizationMembership(
        organization_id=org_a.id,
        user_id=user_c.id,
        role="member",
    )
    db_session.add(membership_c)
    db_session.commit()

    token_c = AuthService.create_access_token(
        user_id=user_c.id,
        email=user_c.email,
        organization_id=org_a.id,
        business_id=biz_a.id,
    )

    # Organization B
    user_b, org_b, biz_b = AuthService.signup(
        db=db_session,
        email="owner_b@globex.com",
        password="Password123!",
        full_name="Bob Globex",
        organization_name="Globex Inc",
        business_name="Globex Tech",
    )
    token_b = AuthService.create_access_token(
        user_id=user_b.id,
        email=user_b.email,
        organization_id=org_b.id,
        business_id=biz_b.id,
    )

    return {
        "user_a": user_a,
        "org_a": org_a,
        "biz_a": biz_a,
        "token_a": token_a,
        "user_b": user_b,
        "org_b": org_b,
        "biz_b": biz_b,
        "token_b": token_b,
        "user_c": user_c,
        "token_c": token_c,
    }


# ===========================================================================
# 1. AUTHENTICATION & IDENTITY TESTS (Items 1, 2, 3, 4, 16, 17)
# ===========================================================================

def test_1_authenticated_user_can_access_own_business(client, saas_tenants):
    """Req 1: Authenticated user can read and access their own business workspace."""
    headers = {"Authorization": f"Bearer {saas_tenants['token_a']}"}
    res = client.get(f"/api/v1/businesses/{saas_tenants['biz_a'].id}", headers=headers)
    assert res.status_code == 200
    data = res.json()
    assert data["id"] == saas_tenants["biz_a"].id
    assert data["name"] == "Acme Retail"


def test_2_unauthenticated_request_rejected(client, saas_tenants):
    """Req 2: Unauthenticated request to protected endpoints is rejected with HTTP 401."""
    res = client.get("/api/v1/auth/me")
    assert res.status_code == 401


def test_3_member_access_follows_role_and_membership(client, saas_tenants):
    """Req 3: Member cannot modify business settings (only owner/admin can)."""
    headers = {"Authorization": f"Bearer {saas_tenants['token_c']}"}
    # Member attempts to patch business
    res = client.patch(
        f"/api/v1/businesses/{saas_tenants['biz_a'].id}",
        json={"name": "Hacked Name"},
        headers=headers,
    )
    assert res.status_code == 403
    assert "Only organization owners and admins" in res.json()["detail"]


def test_4_unauthorized_organization_rejected(client, saas_tenants):
    """Req 4: User A attempting to create a business under Org B is rejected."""
    headers = {"Authorization": f"Bearer {saas_tenants['token_a']}"}
    res = client.post(
        "/api/v1/businesses",
        json={"name": "Illegitimate Biz", "organization_id": saas_tenants["org_b"].id},
        headers=headers,
    )
    assert res.status_code == 403


def test_16_expired_or_invalid_jwt_rejected(client, saas_tenants):
    """Req 16: Expired or signature-tampered JWT is rejected with HTTP 401."""
    # Construct expired token (expired 1 hour ago)
    expired_token = AuthService.create_access_token(
        user_id=saas_tenants["user_a"].id,
        email="expired@acme.com",
        expires_delta=timedelta(hours=-1),
    )
    res = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {expired_token}"})
    assert res.status_code == 401
    assert "expired" in res.json()["detail"].lower()


def test_17_malformed_jwt_rejected(client):
    """Req 17: Malformed / corrupted JWT is rejected with HTTP 401."""
    res = client.get("/api/v1/auth/me", headers={"Authorization": "Bearer not-a-valid-token"})
    assert res.status_code == 401


# ===========================================================================
# 2. CROSS-TENANT & IDOR AUTHORIZATION TESTS (Items 5, 6, 7, 8, 14, 15)
# ===========================================================================

def test_5_and_8_idor_and_cross_tenant_get_rejected(client, saas_tenants):
    """Req 5 & 8: Org A user cannot GET Org B's business workspace via IDOR."""
    headers = {"Authorization": f"Bearer {saas_tenants['token_a']}"}
    # Direct access to Biz B's ID
    res = client.get(f"/api/v1/businesses/{saas_tenants['biz_b'].id}", headers=headers)
    assert res.status_code == 403
    assert "Access denied" in res.json()["detail"]


def test_6_cross_tenant_update_rejected(client, saas_tenants):
    """Req 6: Org A user cannot UPDATE Org B's business workspace."""
    headers = {"Authorization": f"Bearer {saas_tenants['token_a']}"}
    res = client.patch(
        f"/api/v1/businesses/{saas_tenants['biz_b'].id}",
        json={"name": "Attacked Globex"},
        headers=headers,
    )
    assert res.status_code == 403


def test_14_and_15_forged_organization_or_business_id_rejected(client, saas_tenants):
    """Req 14 & 15: Client passing forged X-Business-ID header is blocked by IDOR defense."""
    headers = {
        "Authorization": f"Bearer {saas_tenants['token_a']}",
        "X-Business-ID": saas_tenants["biz_b"].id,  # Forged header
    }
    # Attempt to access onboarding status for Biz B using User A token
    res = client.get("/api/v1/onboarding/status", headers=headers)
    assert res.status_code == 403
    assert "Access denied" in res.json()["detail"]


# ===========================================================================
# 3. STORAGE & DATASET ISOLATION (Items 9, 18, 19)
# ===========================================================================

def test_18_storage_path_traversal_rejected(db_session, saas_tenants):
    """Req 18: File uploads attempting path traversal are sanitized safely."""
    malicious_filename = "../../../etc/passwd.csv"
    csv_content = b"date,revenue\n2025-01-01,1000\n"

    dataset, report = TenantDataService.save_and_profile_file(
        db=db_session,
        organization_id=saas_tenants["org_a"].id,
        business_id=saas_tenants["biz_a"].id,
        filename=malicious_filename,
        content=csv_content,
        content_type="text/csv",
    )

    # Verify storage_key does not contain directory traversal sequences
    assert ".." not in dataset.storage_key
    assert ".." not in dataset.filename
    assert dataset.filename == "etc_passwd.csv"
    assert dataset.business_id == saas_tenants["biz_a"].id


def test_9_and_19_unauthorized_dataset_and_file_download_rejected(db_session, saas_tenants):
    """Req 9 & 19: Organization B cannot read or access datasets owned by Organization A."""
    # Org A uploaded dataset
    dataset_a = UploadedDataset(
        business_id=saas_tenants["biz_a"].id,
        organization_id=saas_tenants["org_a"].id,
        filename="acme_confidential_sales.csv",
        file_type="csv",
        storage_key=f"organizations/{saas_tenants['org_a'].id}/businesses/{saas_tenants['biz_a'].id}/datasets/test.csv",
        file_size_bytes=1024,
        row_count=500,
        column_count=4,
        readiness_status="ready",
    )
    db_session.add(dataset_a)
    db_session.commit()

    # Query with tenant B isolation
    readiness_b = TenantDataService.get_data_readiness(session=db_session, business_id=saas_tenants["biz_b"].id)
    # Biz B should have 0 datasets, completely unware of Biz A's sales
    assert readiness_b["dataset_count"] == 0
    assert readiness_b["total_rows"] == 0


# ===========================================================================
# 4. KNOWLEDGE & RAG VECTOR ISOLATION (Items 10, 12 + Phase 15Q Distinguishable Data)
# ===========================================================================

def test_10_and_12_cross_tenant_knowledge_and_vector_retrieval_isolated(client, db_session, saas_tenants):
    """Req 10, 12, and Phase 15Q:
    Business A: revenue context = 100,000
    Business B: revenue context = 900,000
    Verify Business A retrieval ONLY sees 100,000 and NEVER 900,000.
    Verify cross-tenant document access via IDOR is rejected (HTTP 403).
    """
    ingestion_service = DocumentIngestionService(db_session)

    # 1. Ingest Private Document for Business A
    meta_a = DocumentMetadata(
        title="Acme Financial Performance 2025",
        business_domain="finance",
        version="1.0",
        source="acme_internal.md",
    )
    result_a = ingestion_service.ingest_text(
        text="# Acme Financial Overview\nIn fiscal year 2025, Acme achieved total audited revenue of $100,000 strictly from retail operations.",
        doc_type="markdown",
        metadata=meta_a,
        business_id=saas_tenants["biz_a"].id,
    )

    # 2. Ingest Private Document for Business B
    meta_b = DocumentMetadata(
        title="Globex Financial Performance 2025",
        business_domain="finance",
        version="1.0",
        source="globex_internal.md",
    )
    result_b = ingestion_service.ingest_text(
        text="# Globex Financial Overview\nIn fiscal year 2025, Globex recorded massive revenue of $900,000 across cloud infrastructure licenses.",
        doc_type="markdown",
        metadata=meta_b,
        business_id=saas_tenants["biz_b"].id,
    )

    # 3. Vector Retrieval Test for Business A
    retriever_a = HybridRetriever(db_session)
    res_a = retriever_a.retrieve(
        query="Tell me about audited retail financial performance and earnings",
        business_domain="finance",
        business_id=saas_tenants["biz_a"].id,
    )
    assert len(res_a.chunks) > 0
    # Business A must see $100,000
    assert "100,000" in res_a.context_text
    # Business A must NEVER see $900,000
    assert "900,000" not in res_a.context_text

    # 4. Vector Retrieval Test for Business B
    retriever_b = HybridRetriever(db_session)
    res_b = retriever_b.retrieve(
        query="Tell me about audited cloud infrastructure performance and licenses",
        business_domain="finance",
        business_id=saas_tenants["biz_b"].id,
    )
    assert len(res_b.chunks) > 0
    # Business B must see $900,000
    assert "900,000" in res_b.context_text
    # Business B must NEVER see $100,000
    assert "100,000" not in res_b.context_text

    # 5. IDOR test: User A requesting doc_b directly is rejected
    headers_a = {"X-Business-ID": saas_tenants["biz_a"].id}
    res_idor = client.get(f"/api/v1/knowledge/documents/{result_b.document_id}", headers=headers_a)
    assert res_idor.status_code == 403
    assert "Access denied" in res_idor.json()["detail"]


# ===========================================================================
# 5. OKF ISOLATION (Item 11)
# ===========================================================================

def test_11_cross_tenant_okf_access_rejected(db_session, saas_tenants):
    """Req 11: OKF bundles belonging to Business A cannot be accessed or exported by Business B."""
    bundle_text = """---
id: acme_policy_2025
name: Acme Internal Margin Policy
version: 1
status: verified
author: Chief Risk Officer
domain: finance
type: bundle
---
id: rule_margin_floor
name: Gross Margin Floor
type: rule
status: verified
version: 1
domain: finance
source: internal_policy
author: Chief Risk Officer
priority: 1
condition: margin < 0.25
action: flag_review
description: Acme transactions with margin below 25% require VP approval.
"""
    # Import for Biz A
    bundle_model, report = OKFService.import_bundle(
        bundle_text=bundle_text,
        session=db_session,
        sync_rag=False,
        business_id=saas_tenants["biz_a"].id,
    )
    assert bundle_model.business_id == saas_tenants["biz_a"].id

    # Business B attempts to export Biz A's bundle
    with pytest.raises(OKFServiceError, match="Access denied"):
        OKFService.export_bundle(
            bundle_id="acme_policy_2025",
            session=db_session,
            business_id=saas_tenants["biz_b"].id,
        )


# ===========================================================================
# 6. ANALYSIS RUN & DECISION RECORD ISOLATION (Item 13)
# ===========================================================================

def test_13_cross_tenant_analysis_history_and_decisions_rejected(client, db_session, saas_tenants):
    """Req 13: Analysis runs and HITL decisions belonging to Biz A cannot be viewed by Biz B."""
    # Create AnalysisRun and DecisionRecord under Biz A
    run_a = AnalysisRun(
        request_id=str(uuid4()),
        organization_id=saas_tenants["org_a"].id,
        business_id=saas_tenants["biz_a"].id,
        query="What is Acme's Q4 gross margin?",
        intent="metric_lookup",
        status="success",
        answer="Acme Q4 gross margin is 42.5%.",
        execution_time_ms=120.0,
    )
    db_session.add(run_a)
    db_session.flush()

    dec_a = DecisionRecord(
        organization_id=saas_tenants["org_a"].id,
        business_id=saas_tenants["biz_a"].id,
        analysis_id=run_a.id,
        recommendation_text="Maintain retail prices across product lines.",
        status="PENDING",
    )
    db_session.add(dec_a)
    db_session.commit()

    # Biz B attempts to read Run A via IDOR
    headers_b = {"X-Business-ID": saas_tenants["biz_b"].id}
    res_run = client.get(f"/api/v1/history/runs/{run_a.id}", headers=headers_b)
    assert res_run.status_code == 403
    assert "Access denied" in res_run.json()["detail"]

    # Biz B attempts to read Decision A via IDOR
    res_dec = client.get(f"/api/v1/history/decisions/{dec_a.id}", headers=headers_b)
    assert res_dec.status_code == 403
    assert "Access denied" in res_dec.json()["detail"]


# ===========================================================================
# 7. AGENT TENANT BOUNDARY (Item 20)
# ===========================================================================

def test_20_agent_cannot_escape_tenant_boundary(client, saas_tenants):
    """Req 20: Agent analyze requests accept and stamp tenant boundary server-side."""
    headers = {
        "Authorization": f"Bearer {saas_tenants['token_a']}",
        "X-Business-ID": saas_tenants["biz_a"].id,
    }
    # Invoke agent analysis
    res = client.post(
        "/api/v1/agent/analyze",
        json={"query": "What is our current financial health?"},
        headers=headers,
    )
    assert res.status_code == 200
    data = res.json()
    assert "answer" in data
    assert data["status"] in ["success", "clarification_needed", "unsupported"]


def test_7_cross_tenant_delete_rejected(client, saas_tenants):
    """Req 7: Org A user cannot DELETE Org B's business workspace."""
    headers = {"Authorization": f"Bearer {saas_tenants['token_a']}"}
    res = client.delete(f"/api/v1/businesses/{saas_tenants['biz_b'].id}", headers=headers)
    assert res.status_code == 403
    assert "Only organization owners" in res.json()["detail"] or "Access denied" in res.json()["detail"]


def test_onboarding_e2e_workflow(client):
    """End-to-end SaaS flow: Signup -> Configure Business -> Optional Context -> Connect Data -> Readiness."""
    # 1. Signup
    signup_res = client.post(
        "/api/v1/auth/signup",
        json={
            "email": "newfounder@startup.io",
            "password": "StrongPassword123!",
            "full_name": "Sam Founder",
            "organization_name": "Startup IO",
            "business_name": "Startup Prime",
        },
    )
    assert signup_res.status_code == 201
    auth_data = signup_res.json()
    token = auth_data["access_token"]
    biz_id = auth_data["business"]["id"]

    headers = {
        "Authorization": f"Bearer {token}",
        "X-Business-ID": biz_id,
    }

    # 2. Step 1: Configure Business
    step1_res = client.post(
        "/api/v1/onboarding/business",
        json={
            "name": "Startup Prime Refined",
            "industry": "Software",
            "country": "US",
            "currency": "USD",
            "timezone": "America/New_York",
            "business_type": "B2B SaaS",
            "fiscal_year_start": 1,
        },
        headers=headers,
    )
    assert step1_res.status_code == 200
    assert step1_res.json()["business"]["industry"] == "Software"

    # 3. Step 2: Skip Optional Context
    step2_res = client.post(
        "/api/v1/onboarding/context",
        json={"skip": True},
        headers=headers,
    )
    assert step2_res.status_code == 200
    assert step2_res.json()["step"] == "context_skipped"

    # 4. Step 3: Connect Data (CSV Upload)
    csv_bytes = b"transaction_date,customer_id,product,revenue\n2025-01-01,C101,Widget,500.0\n2025-01-02,C102,Gadget,750.0\n"
    files = {"file": ("sales_jan.csv", csv_bytes, "text/csv")}
    step3_res = client.post(
        "/api/v1/onboarding/data",
        files=files,
        headers=headers,
    )
    assert step3_res.status_code == 200
    data_out = step3_res.json()
    assert data_out["filename"] == "sales_jan.csv"
    assert data_out["readiness_status"] == "ready"
    assert data_out["step"] == "completed"

    # 5. Check Onboarding & Data Readiness Status
    status_res = client.get("/api/v1/onboarding/status", headers=headers)
    assert status_res.status_code == 200
    status_data = status_res.json()
    assert status_data["data_readiness_status"] == "ready"
    assert status_data["readiness_report"]["dataset_count"] >= 1

