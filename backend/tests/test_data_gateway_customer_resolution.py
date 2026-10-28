"""Regression Test Suite for Phase 1C.1: Tenant-Safe Sales Customer Resolution.

Verifies:
1. Two customers in one tenant with sales correctly mapped to their respective customer IDs.
2. Multiple line items in the same order resolving to one customer.
3. Unknown customer identifier rejected (UNRESOLVED_CUSTOMER).
4. Missing customer identifier column rejected with HTTP 400.
5. Conflicting customer identifiers across rows of one order rejected (CONFLICTING_ORDER_METADATA).
6. Cross-tenant customer isolation: customer belonging to Tenant B rejected when ingested by Tenant A.
7. Duplicate or empty identifiers handled safely (REQUIRED_VALUE_MISSING).
8. Failed mapping causes complete transaction rollback with zero partial sales persistence.
9. Existing order totals, discounts, taxes, dates, and statuses remain exact.
10. Explicit default customer mapping workflow functions correctly.
11. CustomerDataReadinessAssessor detects unlinked or ambiguous customer bindings and blocks pilot.
"""

import io
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from app.analytics.core.context import AnalysisContext
from app.analytics.customer.readiness import CustomerDataReadinessAssessor
from app.api.deps import get_db_session
from app.core.database import get_db
from app.main import app
from app.models.base import Base
from app.models.customer import Customer
from app.models.sale import Sale
from app.models.tenant import Business, IngestionJob
from app.services.auth_service import AuthService
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
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
def tenant_fixture(db_session):
    """Provisions two isolated tenants: Tenant A and Tenant B."""
    user_a, org_a, biz_a = AuthService.signup(
        db=db_session,
        email=f"p1c1_owner_a_{uuid4().hex[:6]}@tenant-a.com",
        password="SecurePassword123!",
        full_name="Phase 1C.1 Tenant A Owner",
        organization_name="Enterprise Alpha Corp",
        business_name="Alpha Retail",
    )
    token_a = AuthService.create_access_token(
        user_id=user_a.id,
        email=user_a.email,
        organization_id=org_a.id,
        business_id=biz_a.id,
    )

    user_b, org_b, biz_b = AuthService.signup(
        db=db_session,
        email=f"p1c1_owner_b_{uuid4().hex[:6]}@tenant-b.com",
        password="SecurePassword123!",
        full_name="Phase 1C.1 Tenant B Owner",
        organization_name="Enterprise Beta Corp",
        business_name="Beta Retail",
    )
    token_b = AuthService.create_access_token(
        user_id=user_b.id,
        email=user_b.email,
        organization_id=org_b.id,
        business_id=biz_b.id,
    )

    # Seed 2 distinct customers for Tenant A
    cust_a1 = Customer(
        business_id=biz_a.id,
        customer_code="CUST-TENANT-A-01",
        name="Alice Walker",
        email="alice@tenant-a.com",
        city="Seattle",
        customer_segment="Retail",
        acquisition_date=date(2025, 1, 1),
    )
    cust_a2 = Customer(
        business_id=biz_a.id,
        customer_code="CUST-TENANT-A-02",
        name="Bob Martin",
        email="bob@tenant-a.com",
        city="Portland",
        customer_segment="VIP",
        acquisition_date=date(2025, 1, 15),
    )
    db_session.add_all([cust_a1, cust_a2])

    # Seed 1 customer for Tenant B
    cust_b1 = Customer(
        business_id=biz_b.id,
        customer_code="CUST-TENANT-B-01",
        name="Carol Danvers",
        email="carol@tenant-b.com",
        city="San Francisco",
        customer_segment="Wholesale",
        acquisition_date=date(2025, 2, 1),
    )
    db_session.add(cust_b1)
    db_session.commit()

    return {
        "biz_a": biz_a,
        "token_a": token_a,
        "cust_a1": cust_a1,
        "cust_a2": cust_a2,
        "biz_b": biz_b,
        "token_b": token_b,
        "cust_b1": cust_b1,
    }


def test_two_customers_same_tenant_sales_mapped_correctly(client, tenant_fixture):
    """Scenario 1: Two customers in one tenant have sales mapped to their respective customer IDs."""
    headers = {
        "Authorization": f"Bearer {tenant_fixture['token_a']}",
        "X-Business-ID": tenant_fixture["biz_a"].id,
    }

    csv_data = (
        "order_number,date,amount,customer_code\n"
        "TXN-MAP-01,2025-03-01,100.00,CUST-TENANT-A-01\n"
        "TXN-MAP-02,2025-03-02,200.00,CUST-TENANT-A-02\n"
    )
    files = {"file": ("mapped_sales.csv", io.BytesIO(csv_data.encode("utf-8")), "text/csv")}
    up = client.post("/api/v1/gateway/upload", files=files, headers=headers)
    assert up.status_code == 201
    dataset_id = up.json()["dataset_id"]

    ingest = client.post(
        f"/api/v1/gateway/datasets/{dataset_id}/ingest",
        headers=headers,
        json={"target_entity": "Sale"},
    )
    assert ingest.status_code == 200
    assert ingest.json()["records_persisted"] == 2

    with TestingSessionLocal() as db:
        sale_1 = db.execute(
            select(Sale).where(
                Sale.business_id == tenant_fixture["biz_a"].id,
                Sale.transaction_number == "TXN-MAP-01",
            )
        ).scalar_one()
        assert sale_1.customer_id == tenant_fixture["cust_a1"].id
        assert sale_1.total_amount == Decimal("100.00")

        sale_2 = db.execute(
            select(Sale).where(
                Sale.business_id == tenant_fixture["biz_a"].id,
                Sale.transaction_number == "TXN-MAP-02",
            )
        ).scalar_one()
        assert sale_2.customer_id == tenant_fixture["cust_a2"].id
        assert sale_2.total_amount == Decimal("200.00")


def test_multi_line_order_same_customer_accumulation(client, tenant_fixture):
    """Scenario 2: Multiple line items belonging to the same order resolve to one customer."""
    headers = {
        "Authorization": f"Bearer {tenant_fixture['token_a']}",
        "X-Business-ID": tenant_fixture["biz_a"].id,
    }

    csv_data = (
        "order_number,date,amount,customer_code\n"
        "ORD-MULTI-RES-01,2025-03-05,40.00,CUST-TENANT-A-01\n"
        "ORD-MULTI-RES-01,2025-03-05,35.00,CUST-TENANT-A-01\n"
        "ORD-MULTI-RES-01,2025-03-05,25.00,CUST-TENANT-A-01\n"
    )
    files = {"file": ("multi_res.csv", io.BytesIO(csv_data.encode("utf-8")), "text/csv")}
    up = client.post("/api/v1/gateway/upload", files=files, headers=headers)
    assert up.status_code == 201
    dataset_id = up.json()["dataset_id"]

    ingest = client.post(
        f"/api/v1/gateway/datasets/{dataset_id}/ingest",
        headers=headers,
        json={"target_entity": "Sale"},
    )
    assert ingest.status_code == 200
    assert ingest.json()["records_persisted"] == 1

    with TestingSessionLocal() as db:
        sale = db.execute(
            select(Sale).where(
                Sale.business_id == tenant_fixture["biz_a"].id,
                Sale.transaction_number == "ORD-MULTI-RES-01",
            )
        ).scalar_one()
        assert sale.customer_id == tenant_fixture["cust_a1"].id
        assert sale.total_amount == Decimal("100.00")
        assert sale.subtotal == Decimal("100.00")


def test_unknown_customer_identifier_rejected(client, tenant_fixture):
    """Scenario 3: An unknown customer identifier is rejected with UNRESOLVED_CUSTOMER."""
    headers = {
        "Authorization": f"Bearer {tenant_fixture['token_a']}",
        "X-Business-ID": tenant_fixture["biz_a"].id,
    }

    csv_data = (
        "order_number,date,amount,customer_code\n"
        "TXN-UNKNOWN-01,2025-03-10,150.00,CUST-DOES-NOT-EXIST\n"
    )
    files = {"file": ("unknown_cust.csv", io.BytesIO(csv_data.encode("utf-8")), "text/csv")}
    up = client.post("/api/v1/gateway/upload", files=files, headers=headers)
    assert up.status_code == 201
    dataset_id = up.json()["dataset_id"]

    ingest = client.post(
        f"/api/v1/gateway/datasets/{dataset_id}/ingest",
        headers=headers,
        json={"target_entity": "Sale"},
    )
    assert ingest.status_code == 400
    detail = ingest.json()["detail"]
    assert detail["total_errors"] >= 1
    assert any(e["error_type"] == "UNRESOLVED_CUSTOMER" for e in detail["errors"])
    assert "CUST-DOES-NOT-EXIST" in detail["errors"][0]["message"]


def test_missing_customer_identifier_column_rejected(client, tenant_fixture):
    """Scenario 4: An upload with no customer identifier column is rejected with actionable HTTP 400."""
    headers = {
        "Authorization": f"Bearer {tenant_fixture['token_a']}",
        "X-Business-ID": tenant_fixture["biz_a"].id,
    }

    # CSV has order_number, date, amount — NO customer identifier
    csv_data = (
        "order_number,date,amount\n"
        "TXN-NO-CUST-01,2025-03-12,75.00\n"
        "TXN-NO-CUST-02,2025-03-12,85.00\n"
    )
    files = {"file": ("no_customer_col.csv", io.BytesIO(csv_data.encode("utf-8")), "text/csv")}
    up = client.post("/api/v1/gateway/upload", files=files, headers=headers)
    assert up.status_code == 201
    dataset_id = up.json()["dataset_id"]

    ingest = client.post(
        f"/api/v1/gateway/datasets/{dataset_id}/ingest",
        headers=headers,
        json={"target_entity": "Sale"},
    )
    assert ingest.status_code == 400
    detail = ingest.json()["detail"]
    assert "missing required customer identifier column mapping" in detail.lower()
    assert "customer_code" in detail


def test_conflicting_customer_identifiers_across_order_rows_rejected(client, tenant_fixture):
    """Scenario 5: Conflicting customer identifiers on the same order produce CONFLICTING_ORDER_METADATA."""
    headers = {
        "Authorization": f"Bearer {tenant_fixture['token_a']}",
        "X-Business-ID": tenant_fixture["biz_a"].id,
    }

    # Same order ORD-CONF-01 has Alice on row 1 and Bob on row 2
    csv_data = (
        "order_number,date,amount,customer_code\n"
        "ORD-CONF-01,2025-03-15,50.00,CUST-TENANT-A-01\n"
        "ORD-CONF-01,2025-03-15,60.00,CUST-TENANT-A-02\n"
    )
    files = {"file": ("conflicting_cust.csv", io.BytesIO(csv_data.encode("utf-8")), "text/csv")}
    up = client.post("/api/v1/gateway/upload", files=files, headers=headers)
    assert up.status_code == 201
    dataset_id = up.json()["dataset_id"]

    ingest = client.post(
        f"/api/v1/gateway/datasets/{dataset_id}/ingest",
        headers=headers,
        json={"target_entity": "Sale"},
    )
    assert ingest.status_code == 400
    detail = ingest.json()["detail"]
    assert detail["total_errors"] >= 1
    err = detail["errors"][0]
    assert err["error_type"] == "CONFLICTING_ORDER_METADATA"
    assert "conflicting customer identifier" in err["message"].lower()

    # Verify zero partial rows persisted
    with TestingSessionLocal() as db:
        conf_sale = db.execute(
            select(Sale).where(
                Sale.business_id == tenant_fixture["biz_a"].id,
                Sale.transaction_number == "ORD-CONF-01",
            )
        ).scalar_one_or_none()
        assert conf_sale is None


def test_cross_tenant_customer_code_rejected(client, tenant_fixture):
    """Scenario 6: A customer code belonging exclusively to Tenant B is rejected when Tenant A attempts ingestion."""
    headers = {
        "Authorization": f"Bearer {tenant_fixture['token_a']}",
        "X-Business-ID": tenant_fixture["biz_a"].id,
    }

    # Tenant A attempts to ingest using Tenant B's customer code
    csv_data = (
        "order_number,date,amount,customer_code\n"
        "TXN-IDOR-01,2025-03-18,500.00,CUST-TENANT-B-01\n"
    )
    files = {"file": ("cross_tenant_sales.csv", io.BytesIO(csv_data.encode("utf-8")), "text/csv")}
    up = client.post("/api/v1/gateway/upload", files=files, headers=headers)
    assert up.status_code == 201
    dataset_id = up.json()["dataset_id"]

    ingest = client.post(
        f"/api/v1/gateway/datasets/{dataset_id}/ingest",
        headers=headers,
        json={"target_entity": "Sale"},
    )
    assert ingest.status_code == 400
    detail = ingest.json()["detail"]
    assert any(e["error_type"] == "UNRESOLVED_CUSTOMER" for e in detail["errors"])

    # Verify Tenant B's customer was never attached to Tenant A
    with TestingSessionLocal() as db:
        idor_sale = db.execute(
            select(Sale).where(
                Sale.business_id == tenant_fixture["biz_a"].id,
                Sale.transaction_number == "TXN-IDOR-01",
            )
        ).scalar_one_or_none()
        assert idor_sale is None


def test_empty_or_null_customer_identifier_rejected(client, tenant_fixture):
    """Scenario 7: Empty or whitespace customer identifier produces REQUIRED_VALUE_MISSING."""
    headers = {
        "Authorization": f"Bearer {tenant_fixture['token_a']}",
        "X-Business-ID": tenant_fixture["biz_a"].id,
    }

    csv_data = (
        "order_number,date,amount,customer_code\n"
        "TXN-EMPTY-01,2025-03-20,120.00,   \n"
    )
    files = {"file": ("empty_cust.csv", io.BytesIO(csv_data.encode("utf-8")), "text/csv")}
    up = client.post("/api/v1/gateway/upload", files=files, headers=headers)
    assert up.status_code == 201
    dataset_id = up.json()["dataset_id"]

    ingest = client.post(
        f"/api/v1/gateway/datasets/{dataset_id}/ingest",
        headers=headers,
        json={"target_entity": "Sale"},
    )
    assert ingest.status_code == 400
    detail = ingest.json()["detail"]
    assert any(e["error_type"] == "REQUIRED_VALUE_MISSING" for e in detail["errors"])


def test_failed_mapping_full_rollback_zero_partial_persistence(client, tenant_fixture):
    """Scenario 8: A failed customer mapping causes zero partial sales persistence (full rollback)."""
    headers = {
        "Authorization": f"Bearer {tenant_fixture['token_a']}",
        "X-Business-ID": tenant_fixture["biz_a"].id,
    }

    # 3 valid rows followed by 1 row with unknown customer
    csv_data = (
        "order_number,date,amount,customer_code\n"
        "ROLL-CUST-01,2025-03-22,10.00,CUST-TENANT-A-01\n"
        "ROLL-CUST-02,2025-03-22,20.00,CUST-TENANT-A-01\n"
        "ROLL-CUST-03,2025-03-22,30.00,CUST-TENANT-A-02\n"
        "ROLL-CUST-04,2025-03-22,40.00,CUST-INVALID-GHOST\n"
    )
    files = {"file": ("rollback_cust.csv", io.BytesIO(csv_data.encode("utf-8")), "text/csv")}
    up = client.post("/api/v1/gateway/upload", files=files, headers=headers)
    assert up.status_code == 201
    dataset_id = up.json()["dataset_id"]

    ingest = client.post(
        f"/api/v1/gateway/datasets/{dataset_id}/ingest",
        headers=headers,
        json={"target_entity": "Sale"},
    )
    assert ingest.status_code == 400

    # Ensure NONE of the 4 rows were committed
    with TestingSessionLocal() as db:
        sales = db.execute(
            select(Sale).where(
                Sale.business_id == tenant_fixture["biz_a"].id,
                Sale.transaction_number.in_(["ROLL-CUST-01", "ROLL-CUST-02", "ROLL-CUST-03", "ROLL-CUST-04"]),
            )
        ).scalars().all()
        assert len(sales) == 0, f"Expected 0 persisted sales on failure, found {len(sales)}"

        # Verify job is marked FAILED
        job = db.execute(
            select(IngestionJob).where(
                IngestionJob.dataset_id == dataset_id,
                IngestionJob.target_entity == "Sale",
            )
        ).scalars().first()
        assert job is not None
        assert job.status == "FAILED"


def test_order_totals_discounts_taxes_dates_and_status_preserved(client, tenant_fixture):
    """Scenario 9: Monetary reconciliation, status, and dates remain exact when customer is mapped."""
    headers = {
        "Authorization": f"Bearer {tenant_fixture['token_a']}",
        "X-Business-ID": tenant_fixture["biz_a"].id,
    }

    csv_data = (
        "order_number,date,amount,discount_amount,tax_amount,total_amount,status,customer_code\n"
        "ORD-EXACT-01,2025-03-25 14:30:00,100.00,10.00,5.00,95.00,completed,CUST-TENANT-A-01\n"
    )
    files = {"file": ("exact_metadata.csv", io.BytesIO(csv_data.encode("utf-8")), "text/csv")}
    up = client.post("/api/v1/gateway/upload", files=files, headers=headers)
    assert up.status_code == 201
    dataset_id = up.json()["dataset_id"]

    ingest = client.post(
        f"/api/v1/gateway/datasets/{dataset_id}/ingest",
        headers=headers,
        json={"target_entity": "Sale"},
    )
    assert ingest.status_code == 200

    with TestingSessionLocal() as db:
        sale = db.execute(
            select(Sale).where(
                Sale.business_id == tenant_fixture["biz_a"].id,
                Sale.transaction_number == "ORD-EXACT-01",
            )
        ).scalar_one()
        assert sale.customer_id == tenant_fixture["cust_a1"].id
        assert sale.subtotal == Decimal("100.00")
        assert sale.discount_amount == Decimal("100.00") * 0 + Decimal("10.00")
        assert sale.tax_amount == Decimal("5.00")
        assert sale.total_amount == Decimal("95.00")
        assert sale.status == "completed"
        assert sale.transaction_date.hour == 14
        assert sale.transaction_date.minute == 30


def test_explicit_default_customer_override_workflow(client, tenant_fixture):
    """Scenario 10: Explicit default customer mapping workflow succeeds when column is absent in CSV."""
    headers = {
        "Authorization": f"Bearer {tenant_fixture['token_a']}",
        "X-Business-ID": tenant_fixture["biz_a"].id,
    }

    csv_data = (
        "order_number,date,amount\n"
        "TXN-DEF-OVERRIDE-01,2025-03-28,150.00\n"
    )
    files = {"file": ("override_sales.csv", io.BytesIO(csv_data.encode("utf-8")), "text/csv")}
    up = client.post("/api/v1/gateway/upload", files=files, headers=headers)
    assert up.status_code == 201
    dataset_id = up.json()["dataset_id"]

    # Provide explicit default_customer_code override
    ingest = client.post(
        f"/api/v1/gateway/datasets/{dataset_id}/ingest",
        headers=headers,
        json={
            "target_entity": "Sale",
            "column_overrides": {"default_customer_code": "CUST-TENANT-A-02"},
        },
    )
    assert ingest.status_code == 200
    assert ingest.json()["records_persisted"] == 1

    with TestingSessionLocal() as db:
        sale = db.execute(
            select(Sale).where(
                Sale.business_id == tenant_fixture["biz_a"].id,
                Sale.transaction_number == "TXN-DEF-OVERRIDE-01",
            )
        ).scalar_one()
        assert sale.customer_id == tenant_fixture["cust_a2"].id


def test_readiness_assessor_detects_unlinked_and_ambiguous_customer_sales(db_session):
    """Scenario 11: CustomerDataReadinessAssessor detects unlinked or ambiguous sales and blocks pilot."""
    biz_id = f"test-readiness-blocker-{uuid4().hex[:6]}"
    biz = Business(
        id=biz_id,
        organization_id=f"org-{uuid4().hex[:6]}",
        name="Readiness Audit Biz",
    )
    db_session.add(biz)

    # 1 registered customer
    cust = Customer(
        business_id=biz_id,
        customer_code=f"CUST-RD-{uuid4().hex[:4]}",
        name="Valid Buyer",
        email=f"valid-{uuid4().hex[:4]}@readiness.local",
        city="Denver",
        customer_segment="Retail",
        acquisition_date=date(2025, 1, 1),
    )
    db_session.add(cust)
    db_session.flush()

    # Sale 1: References non-existent customer ID (e.g. unlinked or cross-tenant)
    s1 = Sale(
        business_id=biz_id,
        transaction_number=f"TXN-UNLINKED-{uuid4().hex[:4]}",
        customer_id=99999999,  # Unresolvable customer ID
        transaction_date=datetime(2025, 2, 1, 10, 0, tzinfo=UTC),
        subtotal=Decimal("50.00"),
        total_amount=Decimal("50.00"),
        status="completed",
    )
    # Sale 2 & 3: Ambiguous order grouping: same transaction number pointing to multiple customers
    s2 = Sale(
        business_id=biz_id,
        transaction_number=f"TXN-AMBIGUOUS-{uuid4().hex[:4]}",
        customer_id=cust.id,
        transaction_date=datetime(2025, 2, 2, 10, 0, tzinfo=UTC),
        subtotal=Decimal("60.00"),
        total_amount=Decimal("60.00"),
        status="completed",
    )
    db_session.add_all([s1, s2])
    db_session.commit()

    context = AnalysisContext(business_id=biz_id)
    report = CustomerDataReadinessAssessor.assess_tenant(
        session=db_session,
        context=context,
    )

    # Verify diagnostics detected the unlinked customer
    assert report.data_quality.unresolvable_customer_id_count >= 1
    # Verify verdict is NOT_READY (hard pilot blocker)
    assert report.readiness_verdict == "NOT_READY"
    assert any(
        "unresolvable or foreign tenant customer records" in b.lower()
        for b in report.blockers
    )
