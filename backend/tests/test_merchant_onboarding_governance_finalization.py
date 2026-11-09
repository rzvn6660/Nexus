"""Targeted Regression Test Suite for NEXUS Merchant Onboarding Governance Finalization.

Verifies the three critical analytical governance controls:
1. Customer Resolution:
   - Silent default-anonymous assignment is strictly prohibited on real operational merchants.
   - Anonymous mapping permitted only via explicit, audited manager-approved policy.
   - Unresolved customer rows are quarantined.
   - Cross-tenant customer assignment is strictly prevented.
   - Distinct customers within a tenant are preserved without collapsing.
2. Source Completeness:
   - Zero calendar date gaps does NOT certify completeness.
   - Requires authoritative source evidence, reporting-period boundaries, and reconciliation.
   - Remains SOURCE_COMPLETENESS_UNVERIFIED when evidence is insufficient.
   - Preserves distinction between source completeness verification and signed period-close certification.
3. Import Authorization:
   - Written merchant authorization required before processing real merchant data.
   - Authorization ref or verified metadata permits processing.
   - Merchant files are protected by .gitignore.
"""

import io
import subprocess
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from app.analytics.analyst.models import ExecutionContext
from app.analytics.analyst.skills.quality import SourceCompletenessSkill
from app.analytics.onboarding.postgres_service import PostgreSQLOnboardingService
from app.api.deps import get_db_session
from app.core.database import get_db
from app.main import app
from app.models.base import Base
from app.models.customer import Customer
from app.models.sale import Sale
from app.models.tenant import Business
from app.models.watermark import TenantIngestionWatermark
from app.services.auth_service import AuthService
from app.services.watermark_service import WatermarkCertificationState
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

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
def real_merchant_fixture(db_session: Session):
    """Provisions a protected real operational merchant (Apex Specialty Commerce)."""
    user, org, biz = AuthService.signup(
        db=db_session,
        email=f"compliance_officer_{uuid4().hex[:6]}@apexcommerce.com",
        password="SecurePassword123!",
        full_name="Apex Compliance Officer",
        organization_name="Apex Specialty Commerce Inc",
        business_name="Apex Specialty Commerce",
    )
    token = AuthService.create_access_token(
        user_id=user.id,
        email=user.email,
        organization_id=org.id,
        business_id=biz.id,
    )

    # Seed an existing registered customer
    cust = Customer(
        business_id=biz.id,
        customer_code="APEX-REG-001",
        name="Apex Primary Client",
        email="client1@apex.com",
        city="Chicago",
        customer_segment="Enterprise",
        acquisition_date=date(2025, 1, 1),
    )
    db_session.add(cust)
    db_session.commit()

    return {
        "user": user,
        "org": org,
        "biz": biz,
        "token": token,
        "cust": cust,
    }


# ==============================================================================
# 1. Customer Resolution Governance Tests
# ==============================================================================


def test_silent_default_anonymous_assignment_blocked_on_real_merchant(
    client: TestClient, real_merchant_fixture: dict
):
    """Verify that uploading sales without customer mapping on a real operational merchant is blocked."""
    headers = {
        "Authorization": f"Bearer {real_merchant_fixture['token']}",
        "X-Business-ID": real_merchant_fixture["biz"].id,
    }

    csv_data = (
        "order_number,date,amount\n"
        "APEX-TXN-01,2025-04-01,250.00\n"
        "APEX-TXN-02,2025-04-02,350.00\n"
    )
    files = {"file": ("unmapped_apex_sales.csv", io.BytesIO(csv_data.encode("utf-8")), "text/csv")}
    up = client.post("/api/v1/gateway/upload", files=files, headers=headers)
    assert up.status_code == 201
    dataset_id = up.json()["dataset_id"]

    # Ingestion attempt without explicit audited anonymous policy
    # Providing authorization ref to test customer governance boundary specifically
    ingest = client.post(
        f"/api/v1/gateway/datasets/{dataset_id}/ingest",
        headers=headers,
        json={
            "target_entity": "Sale",
            "column_overrides": {
                "written_authorization_ref": "AUTH-APEX-WRITTEN-2026",
            },
        },
    )
    assert ingest.status_code == 400
    detail = ingest.json()["detail"]
    assert "Silent default-anonymous assignment is prohibited" in detail
    assert "allow_anonymous_customer" in detail


def test_audited_manager_approved_anonymous_policy_authorized(
    client: TestClient, real_merchant_fixture: dict
):
    """Verify that explicit audited manager approval permits anonymous checkout mapping."""
    headers = {
        "Authorization": f"Bearer {real_merchant_fixture['token']}",
        "X-Business-ID": real_merchant_fixture["biz"].id,
    }

    csv_data = (
        "order_number,date,amount\n"
        "APEX-POS-01,2025-04-05,125.00\n"
        "APEX-POS-02,2025-04-06,175.00\n"
    )
    files = {"file": ("pos_anonymous_sales.csv", io.BytesIO(csv_data.encode("utf-8")), "text/csv")}
    up = client.post("/api/v1/gateway/upload", files=files, headers=headers)
    assert up.status_code == 201
    dataset_id = up.json()["dataset_id"]

    # Ingestion with audited manager approval
    ingest = client.post(
        f"/api/v1/gateway/datasets/{dataset_id}/ingest",
        headers=headers,
        json={
            "target_entity": "Sale",
            "column_overrides": {
                "written_authorization_ref": "AUTH-APEX-WRITTEN-2026",
                "allow_anonymous_customer": True,
                "anonymous_policy_approved_by": "vp_operations@apexcommerce.com",
            },
        },
    )
    assert ingest.status_code == 200
    assert ingest.json()["records_persisted"] == 2

    with TestingSessionLocal() as db:
        sales = db.execute(
            select(Sale).where(
                Sale.business_id == real_merchant_fixture["biz"].id,
                Sale.transaction_number.in_(["APEX-POS-01", "APEX-POS-02"]),
            )
        ).scalars().all()
        assert len(sales) == 2
        for s in sales:
            assert s.customer_id is not None
            cust = db.execute(select(Customer).where(Customer.id == s.customer_id)).scalar_one()
            assert "ANON" in cust.customer_code
            assert cust.business_id == real_merchant_fixture["biz"].id


def test_cross_tenant_customer_misassignment_prohibited(client: TestClient, db_session: Session):
    """Verify that a customer belonging to Tenant B cannot be mapped or assigned to Tenant A."""
    # Create Tenant A and Tenant B
    user_a, org_a, biz_a = AuthService.signup(
        db=db_session,
        email=f"owner_a_{uuid4().hex[:6]}@domain-a.com",
        password="Password123!",
        full_name="Owner A",
        organization_name="Org A",
        business_name=f"Business A {uuid4().hex[:4]}",
    )
    token_a = AuthService.create_access_token(
        user_id=user_a.id, email=user_a.email, organization_id=org_a.id, business_id=biz_a.id
    )

    _user_b, _org_b, biz_b = AuthService.signup(
        db=db_session,
        email=f"owner_b_{uuid4().hex[:6]}@domain-b.com",
        password="Password123!",
        full_name="Owner B",
        organization_name="Org B",
        business_name=f"Business B {uuid4().hex[:4]}",
    )

    # Register Customer exclusively under Tenant B
    cust_b = Customer(
        business_id=biz_b.id,
        customer_code="CUST-TENANT-B-ONLY",
        name="Tenant B VIP Buyer",
        email="vip@tenant-b.com",
        city="Chicago",
        customer_segment="VIP",
        acquisition_date=date(2025, 1, 1),
    )
    db_session.add(cust_b)
    db_session.commit()

    # Attempt to ingest sales in Tenant A referencing Customer B's code
    headers = {"Authorization": f"Bearer {token_a}", "X-Business-ID": biz_a.id}
    csv_data = (
        "order_number,date,amount,customer_code\n"
        "TXN-ATTACK-01,2025-04-10,100.00,CUST-TENANT-B-ONLY\n"
    )
    files = {"file": ("cross_tenant_probe.csv", io.BytesIO(csv_data.encode("utf-8")), "text/csv")}
    up = client.post("/api/v1/gateway/upload", files=files, headers=headers)
    assert up.status_code == 201
    dataset_id = up.json()["dataset_id"]

    ingest = client.post(
        f"/api/v1/gateway/datasets/{dataset_id}/ingest",
        headers=headers,
        json={"target_entity": "Sale"},
    )
    assert ingest.status_code == 400
    errors = ingest.json()["detail"]["errors"]
    assert any(e["error_type"] == "UNRESOLVED_CUSTOMER" for e in errors)
    assert any(e.get("quarantined") is True for e in errors)


def test_cross_customer_misassignment_prohibited_distinct_attribution(
    client: TestClient, db_session: Session
):
    """Verify that multiple customers in a file are mapped to distinct customer IDs and never collapsed."""
    user, org, biz = AuthService.signup(
        db=db_session,
        email=f"owner_distinct_{uuid4().hex[:6]}@store.com",
        password="Password123!",
        full_name="Owner Distinct",
        organization_name="Distinct Retail Org",
        business_name=f"Distinct Retail Store {uuid4().hex[:4]}",
    )
    token = AuthService.create_access_token(
        user_id=user.id, email=user.email, organization_id=org.id, business_id=biz.id
    )

    c1 = Customer(
        business_id=biz.id,
        customer_code="CUST-ALPHA-01",
        name="Customer Alpha",
        email="alpha@store.com",
        city="Austin",
        customer_segment="Retail",
        acquisition_date=date(2025, 1, 1),
    )
    c2 = Customer(
        business_id=biz.id,
        customer_code="CUST-BETA-02",
        name="Customer Beta",
        email="beta@store.com",
        city="Dallas",
        customer_segment="VIP",
        acquisition_date=date(2025, 1, 1),
    )
    db_session.add_all([c1, c2])
    db_session.commit()

    headers = {"Authorization": f"Bearer {token}", "X-Business-ID": biz.id}
    csv_data = (
        "order_number,date,amount,customer_code\n"
        "ORD-DISTINCT-01,2025-04-11,100.00,CUST-ALPHA-01\n"
        "ORD-DISTINCT-02,2025-04-12,200.00,CUST-BETA-02\n"
    )
    files = {"file": ("distinct_customers.csv", io.BytesIO(csv_data.encode("utf-8")), "text/csv")}
    up = client.post("/api/v1/gateway/upload", files=files, headers=headers)
    dataset_id = up.json()["dataset_id"]

    ingest = client.post(
        f"/api/v1/gateway/datasets/{dataset_id}/ingest",
        headers=headers,
        json={"target_entity": "Sale"},
    )
    assert ingest.status_code == 200
    assert ingest.json()["records_persisted"] == 2

    with TestingSessionLocal() as db:
        s1 = db.execute(select(Sale).where(Sale.transaction_number == "ORD-DISTINCT-01")).scalar_one()
        s2 = db.execute(select(Sale).where(Sale.transaction_number == "ORD-DISTINCT-02")).scalar_one()

        # Exact, distinct customer foreign keys
        assert s1.customer_id == c1.id
        assert s2.customer_id == c2.id
        assert s1.customer_id != s2.customer_id


def test_postgres_onboarding_quarantines_missing_customer_without_audited_policy(
    db_session: Session, real_merchant_fixture: dict
):
    """Verify PostgreSQL onboarding quarantines unmapped customer rows when no policy is approved."""
    biz = real_merchant_fixture["biz"]

    with patch("psycopg.connect") as mock_connect:
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_connect.return_value.__enter__.return_value = mock_conn
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur

        mock_cur.description = [("order_id",), ("total",), ("date",), ("status",)]
        mock_cur.fetchall.return_value = [
            ("PG-QUARANTINE-01", "150.00", "2026-10-15T12:00:00", "completed"),
        ]

        # Ingestion WITHOUT allow_anonymous_customer
        res = PostgreSQLOnboardingService.ingest_table_to_canonical(
            db=db_session,
            business_id=biz.id,
            host="127.0.0.1",
            port=5432,
            database="testdb",
            user="user",
            password="pwd",
            table_name="orders",
            target_entity="Sale",
            column_mapping={
                "order_number": "order_id",
                "amount": "total",
                "date": "date",
                "status": "status",
                "written_authorization_ref": "AUTH-APEX-WRITTEN-2026",
            },
        )

        assert res["success"] is True
        assert res["inserted_count"] == 0
        assert res["rejected_count"] == 1
        assert res["rejected_records"][0]["quarantined"] is True
        assert "Unresolved customer" in res["rejected_records"][0]["reason"]


# ==============================================================================
# 2. Source Completeness Governance Tests
# ==============================================================================


def test_source_completeness_unverified_despite_zero_date_gaps(db_session: Session):
    """Verify that zero date gaps alone does NOT certify completeness without authoritative evidence."""
    suffix = uuid4().hex[:6]
    biz = Business(
        id=f"biz-gap-test-{suffix}",
        organization_id=f"org-{suffix}",
        name=f"Gap Test Business {suffix}",
        currency="USD",
    )
    cust = Customer(
        business_id=biz.id,
        customer_code=f"CUST-GAP-{suffix}",
        name="Gap Test Buyer",
        email=f"buyer_{suffix}@test.local",
        city="Denver",
        customer_segment="Retail",
        acquisition_date=date(2025, 1, 1),
    )
    db_session.add_all([biz, cust])
    db_session.flush()

    # Seed 5 consecutive days of sales (Zero date gaps)
    base_dt = datetime(2025, 3, 1, 10, 0, tzinfo=UTC)
    for i in range(5):
        s = Sale(
            business_id=biz.id,
            transaction_number=f"TXN-GAP-{suffix}-{i}",
            customer_id=cust.id,
            transaction_date=base_dt + timedelta(days=i),
            subtotal=Decimal("100.00"),
            total_amount=Decimal("100.00"),
            status="completed",
        )
        db_session.add(s)
    db_session.commit()

    context = ExecutionContext(
        business_id=biz.id,
        user_id="user_test",
        user_role="manager",
    )

    skill = SourceCompletenessSkill()
    result = skill.execute(db_session, context)

    assert result.status == "SUCCESS"
    data = result.data
    # Zero calendar gaps detected across recorded span
    assert data["gap_days"] == 0
    assert data["zero_date_gaps"] is True
    # Crucial governance assertion: Completeness MUST remain UNVERIFIED
    assert data["completeness_state"] == "SOURCE_COMPLETENESS_UNVERIFIED"
    assert data["is_period_close_certified"] is False

    # Check that findings clearly explain that zero date gaps != certified completeness
    finding_text = " ".join(result.findings)
    assert "does not establish authoritative source completeness" in finding_text
    assert "Source completeness remains UNVERIFIED" in finding_text


def test_source_completeness_verified_with_boundaries_evidence_and_reconciliation(
    db_session: Session,
):
    """Verify source completeness is VERIFIED when boundaries, watermark evidence, and reconciliation match."""
    suffix = uuid4().hex[:6]
    biz = Business(
        id=f"biz-wm-verified-{suffix}",
        organization_id=f"org-{suffix}",
        name=f"Verified Completeness Biz {suffix}",
        currency="USD",
    )
    cust = Customer(
        business_id=biz.id,
        customer_code=f"CUST-WM-{suffix}",
        name="Watermark Verified Buyer",
        email=f"buyer_{suffix}@test.local",
        city="Denver",
        customer_segment="Retail",
        acquisition_date=date(2025, 1, 1),
    )
    db_session.add_all([biz, cust])
    db_session.flush()

    base_dt = datetime(2025, 3, 1, 10, 0, tzinfo=UTC)
    for i in range(3):
        s = Sale(
            business_id=biz.id,
            transaction_number=f"TXN-WM-{suffix}-{i}",
            customer_id=cust.id,
            transaction_date=base_dt + timedelta(days=i),
            subtotal=Decimal("100.00"),
            total_amount=Decimal("100.00"),
            status="completed",
        )
        db_session.add(s)

    # Establish verified watermark with boundaries, source evidence, and reconciliation
    complete_through = base_dt + timedelta(days=2)
    wm = TenantIngestionWatermark(
        id=str(uuid4()),
        business_id=biz.id,
        source_id="verified_pos_stream",
        complete_through_dt=complete_through,
        provenance_type="batch_file",
        verification_status="verified",
        metadata_json={
            "db_reconciled": True,
            "records_persisted": 3,
            "governance_state": WatermarkCertificationState.SOURCE_COMPLETENESS_VERIFIED.value,
        },
    )
    db_session.add(wm)
    db_session.commit()

    context = ExecutionContext(
        business_id=biz.id,
        user_id="user_test",
        user_role="manager",
    )

    skill = SourceCompletenessSkill()
    result = skill.execute(db_session, context)

    assert result.status == "SUCCESS"
    data = result.data
    assert data["completeness_state"] == "SOURCE_COMPLETENESS_VERIFIED"
    assert data["has_reporting_period_boundaries"] is True
    assert data["has_authoritative_source_evidence"] is True
    assert data["is_source_reconciled"] is True
    # Preserves distinction from period-close certification
    assert data["is_period_close_certified"] is False


# ==============================================================================
# 3. Import Authorization & Security Tests
# ==============================================================================


def test_real_merchant_import_blocked_without_written_authorization(
    client: TestClient, real_merchant_fixture: dict
):
    """Verify real operational merchant import is rejected with HTTP 403 without written authorization."""
    headers = {
        "Authorization": f"Bearer {real_merchant_fixture['token']}",
        "X-Business-ID": real_merchant_fixture["biz"].id,
    }

    csv_data = "order_number,date,amount\nORD-NOAUTH-01,2025-04-01,100.00\n"
    files = {"file": ("unauth_merchant_data.csv", io.BytesIO(csv_data.encode("utf-8")), "text/csv")}
    up = client.post("/api/v1/gateway/upload", files=files, headers=headers)
    assert up.status_code == 201
    dataset_id = up.json()["dataset_id"]

    # Ingest without written_authorization_ref
    ingest = client.post(
        f"/api/v1/gateway/datasets/{dataset_id}/ingest",
        headers=headers,
        json={"target_entity": "Sale"},
    )
    assert ingest.status_code == 403
    assert "Import authorization denied" in ingest.json()["detail"]
    assert "requires verified written merchant authorization" in ingest.json()["detail"]


def test_merchant_files_git_ignored():
    """Verify that merchant data paths are ignored by git to prevent committing actual customer PII."""
    cmd = ["git", "check-ignore", "data/merchant/actual_pos_sales.csv", "sample.merchant.csv", "merchant/raw_data.xlsx"]
    res = subprocess.run(cmd, capture_output=True, text=True, check=False)
    assert res.returncode == 0
    ignored_paths = res.stdout.strip().splitlines()
    assert any("actual_pos_sales.csv" in p for p in ignored_paths)
    assert any("sample.merchant.csv" in p for p in ignored_paths)
    assert any("raw_data.xlsx" in p for p in ignored_paths)


def test_merchant_preview_workflow_and_atomic_rollback(
    client: TestClient, real_merchant_fixture: dict, db_session: Session
):
    """Verify pre-import preview mode leaves zero DB records and failure triggers complete atomic rollback."""
    headers = {
        "Authorization": f"Bearer {real_merchant_fixture['token']}",
        "X-Business-ID": real_merchant_fixture["biz"].id,
    }

    # 1. Upload valid data for preview
    csv_data = (
        "order_number,date,amount,customer_code\n"
        "APEX-PREV-01,2025-04-01,100.00,CUST-UNKNOWN-01\n"
        "APEX-PREV-02,2025-04-02,-50.00,CUST-UNKNOWN-02\n"  # Range error: negative amount
    )
    files = {"file": ("preview_batch.csv", io.BytesIO(csv_data.encode("utf-8")), "text/csv")}
    up = client.post("/api/v1/gateway/upload", files=files, headers=headers)
    assert up.status_code == 201
    dataset_id = up.json()["dataset_id"]

    # 2. Preview endpoint: verifies preview provides data without persisting Sale records
    prev = client.get(f"/api/v1/gateway/datasets/{dataset_id}/preview", headers=headers)
    assert prev.status_code == 200
    preview_data = prev.json()
    assert preview_data["total_rows"] == 2
    assert len(preview_data["sample_rows"]) == 2

    with TestingSessionLocal() as db:
        # Confirm 0 records were persisted during preview
        existing = db.execute(
            select(Sale).where(Sale.transaction_number.in_(["APEX-PREV-01", "APEX-PREV-02"]))
        ).scalars().all()
        assert len(existing) == 0

    # 3. Attempt ingest with invalid row (negative amount)
    ingest = client.post(
        f"/api/v1/gateway/datasets/{dataset_id}/ingest",
        headers=headers,
        json={
            "target_entity": "Sale",
            "column_overrides": {
                "written_authorization_ref": "AUTH-APEX-WRITTEN-2026",
            },
        },
    )
    assert ingest.status_code == 400

    # 4. Confirm complete atomic rollback: APEX-PREV-01 must NOT be saved partially
    with TestingSessionLocal() as db:
        rolled_back = db.execute(
            select(Sale).where(Sale.transaction_number.in_(["APEX-PREV-01", "APEX-PREV-02"]))
        ).scalars().all()
        assert len(rolled_back) == 0
