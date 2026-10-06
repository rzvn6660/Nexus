"""Regression test for tenant Data Readiness mismatch.

Verifies:
1. Tenant Data Readiness reflects actual tenant-scoped UploadedDataset and persisted domain table counts
   (e.g., 60 sales rows + 1 customer row = 61 rows, 1 dataset, status='ready').
2. Tenant isolation is strictly preserved (Tenant B receives 0 datasets and 0 rows without cross-tenant bleed).
3. The /api/v1/onboarding/status endpoint returns both data_readiness and readiness_report
   with identical total_datasets and total_rows counts.
"""

from datetime import UTC, datetime, date
from decimal import Decimal
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.main import app
from app.models.tenant import Business, Organization, OrganizationMembership, UploadedDataset, UserIdentity
from app.models.sale import Sale
from app.models.customer import Customer
from app.services.auth_service import AuthService
from app.services.tenant_data_service import TenantDataService


def _setup_test_tenant(
    db: Session,
    suffix: str,
    sales_rows: int = 60,
    customer_rows: int = 1,
    dataset_rows: int = 60,
) -> tuple[UserIdentity, Business, str]:
    org = Organization(
        id=f"org_rdns_{suffix}",
        name=f"Org Readiness {suffix}",
        slug=f"org-readiness-{suffix}",
    )
    user = UserIdentity(
        id=f"usr_rdns_{suffix}",
        email=f"readiness_{suffix}@nexus.test",
        full_name=f"Readiness User {suffix}",
        password_hash="test_hash",
        is_active=True,
        is_verified=True,
    )
    mem = OrganizationMembership(
        user_id=user.id,
        organization_id=org.id,
        role="owner",
    )
    biz = Business(
        id=f"biz_rdns_{suffix}",
        organization_id=org.id,
        name=f"Readiness Business {suffix}",
        industry="Retail & Distribution",
        country="India",
        currency="INR",
        timezone="UTC",
        fiscal_year_start=1,
        status="active",
        data_readiness_status="ready",
    )
    db.add_all([org, user, mem, biz])
    db.flush()

    if dataset_rows > 0:
        ds = UploadedDataset(
            id=f"ds_rdns_{suffix}",
            organization_id=org.id,
            business_id=biz.id,
            filename="sales.csv",
            file_type="csv",
            storage_key=f"uploads/sales_{suffix}.csv",
            file_size_bytes=2048,
            row_count=dataset_rows,
            column_count=7,
            content_hash=f"hash_rdns_{suffix}",
            readiness_status="READY",
        )
        db.add(ds)

    cust = None
    if customer_rows > 0:
        cust = Customer(
            business_id=biz.id,
            customer_code=f"CUST-{suffix.upper()}",
            name="Default Customer",
            email=f"cust_{suffix}@nexus.test",
            city="Mumbai",
            customer_segment="Retail",
            acquisition_date=date(2026, 1, 1),
        )
        db.add(cust)
        db.flush()

    for i in range(sales_rows):
        sale = Sale(
            business_id=biz.id,
            customer_id=cust.id if cust else 1,
            transaction_number=f"TXN-{suffix}-{i+1:04d}",
            transaction_date=datetime(2026, 1, (i % 28) + 1, 12, 0, tzinfo=UTC),
            subtotal=Decimal("150.00"),
            discount_amount=Decimal("0.00"),
            tax_amount=Decimal("0.00"),
            total_amount=Decimal("150.00"),
            status="completed",
        )
        db.add(sale)

    db.commit()

    token = AuthService.create_access_token(
        user_id=user.id,
        email=user.email,
        organization_id=org.id,
        business_id=biz.id,
    )
    return user, biz, token


def test_tenant_data_readiness_calculation_matches_persisted_state(db_session: Session):
    """Assert Data Readiness calculates actual tenant-scoped dataset and row counts."""
    # Tenant A has 1 dataset (sales.csv, 60 rows), 60 sales rows, and 1 customer row
    _, biz_a, _ = _setup_test_tenant(db_session, "tenant_a", sales_rows=60, customer_rows=1, dataset_rows=60)
    # Tenant B has 0 datasets and 0 domain rows
    _, biz_b, _ = _setup_test_tenant(db_session, "tenant_b", sales_rows=0, customer_rows=0, dataset_rows=0)

    readiness_a = TenantDataService.get_data_readiness(session=db_session, business_id=biz_a.id)
    assert readiness_a["business_id"] == biz_a.id
    assert readiness_a["dataset_count"] == 1
    assert readiness_a["total_datasets"] == 1
    # Total rows must account for actual persisted domain rows: 60 sales + 1 customer = 61 rows
    assert readiness_a["total_rows"] == 61
    assert readiness_a["status"] == "ready"
    assert "sales" in readiness_a["domains_covered"]
    assert "customers" in readiness_a["domains_covered"]
    assert len(readiness_a["datasets"]) == 1
    assert readiness_a["datasets"][0]["filename"] == "sales.csv"

    # Tenant B must remain completely isolated: 0 datasets, 0 rows
    readiness_b = TenantDataService.get_data_readiness(session=db_session, business_id=biz_b.id)
    assert readiness_b["business_id"] == biz_b.id
    assert readiness_b["dataset_count"] == 0
    assert readiness_b["total_datasets"] == 0
    assert readiness_b["total_rows"] == 0
    assert readiness_b["status"] == "not_ready"
    assert readiness_b["domains_covered"] == []


def test_onboarding_status_endpoint_returns_data_readiness_contract(db_session: Session):
    """Assert /api/v1/onboarding/status returns both data_readiness and readiness_report matching frontend."""
    _, biz, token = _setup_test_tenant(db_session, "onb_contract", sales_rows=60, customer_rows=1, dataset_rows=60)

    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    try:
        client = TestClient(app)
        headers = {
            "Authorization": f"Bearer {token}",
            "X-Business-ID": biz.id,
        }
        res = client.get("/api/v1/onboarding/status", headers=headers)
        assert res.status_code == 200
        data = res.json()

        assert "data_readiness" in data
        assert "readiness_report" in data
        assert data["data_readiness_status"] == "ready"

        dr = data["data_readiness"]
        assert dr["total_datasets"] == 1
        assert dr["total_rows"] == 61
        assert dr["status"] == "ready"

        rr = data["readiness_report"]
        assert rr["total_datasets"] == 1
        assert rr["total_rows"] == 61
        assert rr["status"] == "ready"
    finally:
        app.dependency_overrides.pop(get_db, None)
