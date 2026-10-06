"""Regression test for Data Health & Schema Database Catalog and Table Profile consistency.

Verifies:
1. Database Catalog count (/api/v1/data/tables) exactly matches Table Profile count
   (/api/v1/data/profile/{table}) for all registered domain entities.
2. Tenant-scoped customer count consistently equals 1 in both Catalog and Table Profile.
3. Tenant-scoped sales count consistently equals 60 in both Catalog and Table Profile.
4. Total data coverage (/api/v1/data/health total_records) equals the exact sum of catalog counts (61).
5. Multi-tenant isolation is strictly preserved (Tenant B catalog and profile counts do not leak Tenant A data).
"""

from datetime import UTC, datetime, date
from decimal import Decimal
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.main import app
from app.models.tenant import Business, Organization, OrganizationMembership, UserIdentity
from app.models.sale import Sale
from app.models.customer import Customer
from app.services.auth_service import AuthService
from app.data.profiling.profiler import DataProfiler


def _setup_tenant(
    db: Session,
    suffix: str,
    sales_rows: int = 60,
    customer_rows: int = 1,
) -> tuple[UserIdentity, Business, str]:
    org = Organization(
        id=f"org_catprof_{suffix}",
        name=f"Org CatProf {suffix}",
        slug=f"org-catprof-{suffix}",
    )
    user = UserIdentity(
        id=f"usr_catprof_{suffix}",
        email=f"catprof_{suffix}@nexus.test",
        full_name=f"CatProf User {suffix}",
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
        id=f"biz_catprof_{suffix}",
        organization_id=org.id,
        name=f"CatProf Business {suffix}",
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


def test_catalog_count_equals_table_profile_count_for_tenant(db_session: Session):
    """Verify that catalog row count equals table profile cardinality for all tables."""
    _, biz_a, token_a = _setup_tenant(db_session, "tenant_a", sales_rows=60, customer_rows=1)

    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    try:
        client = TestClient(app)
        headers_a = {"Authorization": f"Bearer {token_a}", "X-Business-ID": biz_a.id}

        # 1. Total Data Coverage from /health
        res_health = client.get("/api/v1/data/health", headers=headers_a)
        assert res_health.status_code == 200
        health_data = res_health.json()
        assert health_data["total_records"] == 61

        # 2. Database Catalog from /tables
        res_tables = client.get("/api/v1/data/tables", headers=headers_a)
        assert res_tables.status_code == 200
        tables = res_tables.json()
        catalog_counts = {t["table_name"]: t["row_count"] for t in tables}

        assert catalog_counts["customers"] == 1
        assert catalog_counts["sales"] == 60
        assert sum(catalog_counts.values()) == 61

        # 3. Table Profile for customers
        res_cust = client.get("/api/v1/data/profile/customers", headers=headers_a)
        assert res_cust.status_code == 200
        cust_profile = res_cust.json()

        # Assert Catalog count == Table Profile count (both row_count and total_rows)
        assert cust_profile["row_count"] == catalog_counts["customers"] == 1
        assert cust_profile["total_rows"] == catalog_counts["customers"] == 1

        # 4. Table Profile for sales
        res_sales = client.get("/api/v1/data/profile/sales", headers=headers_a)
        assert res_sales.status_code == 200
        sales_profile = res_sales.json()
        assert sales_profile["row_count"] == catalog_counts["sales"] == 60
        assert sales_profile["total_rows"] == catalog_counts["sales"] == 60

        # 5. Check all other registered tables
        for table_name in ("products", "sale_items", "inventory", "expenses"):
            res_p = client.get(f"/api/v1/data/profile/{table_name}", headers=headers_a)
            assert res_p.status_code == 200
            p = res_p.json()
            assert p["row_count"] == catalog_counts[table_name] == 0
            assert p["total_rows"] == catalog_counts[table_name] == 0

    finally:
        app.dependency_overrides.pop(get_db, None)


def test_catalog_and_profile_preserve_tenant_isolation(db_session: Session):
    """Verify Tenant B does not observe Tenant A's customer or sales records."""
    _, biz_a, _ = _setup_tenant(db_session, "iso_a", sales_rows=60, customer_rows=1)
    _, biz_b, token_b = _setup_tenant(db_session, "iso_b", sales_rows=0, customer_rows=0)

    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    try:
        client = TestClient(app)
        headers_b = {"Authorization": f"Bearer {token_b}", "X-Business-ID": biz_b.id}

        res_health = client.get("/api/v1/data/health", headers=headers_b)
        assert res_health.json()["total_records"] == 0

        res_tables = client.get("/api/v1/data/tables", headers=headers_b)
        tables = res_tables.json()
        catalog_counts = {t["table_name"]: t["row_count"] for t in tables}
        assert catalog_counts["customers"] == 0
        assert catalog_counts["sales"] == 0

        res_cust = client.get("/api/v1/data/profile/customers", headers=headers_b)
        cust_profile = res_cust.json()
        assert cust_profile["row_count"] == 0
        assert cust_profile["total_rows"] == 0

    finally:
        app.dependency_overrides.pop(get_db, None)
