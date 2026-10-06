"""Multi-tenant data isolation regression tests for /api/v1/data endpoints."""

from datetime import datetime, timezone
from decimal import Decimal
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.customer import Customer
from app.models.sale import Sale
from app.models.tenant import Business, Organization, OrganizationMembership, UserIdentity
from app.services.auth_service import AuthService


@pytest.fixture(scope="function")
def two_tenants_data(db_session: Session):
    """Seed two distinct organizations and businesses with isolated customer/sales data."""
    now_utc = datetime.now(timezone.utc)

    # 1. Tenant Alpha
    user_a = UserIdentity(
        id="usr_alpha",
        email="owner@alpha.com",
        full_name="Alpha Owner",
        password_hash=AuthService.hash_password("Password123!"),
        is_active=True,
        is_verified=True,
    )
    org_a = Organization(id="org_alpha", name="Alpha Org", slug="alpha-org")
    biz_a = Business(id="biz_alpha", organization_id=org_a.id, name="Alpha Primary", status="active")
    mem_a = OrganizationMembership(user_id=user_a.id, organization_id=org_a.id, role="owner")

    # 2. Tenant Beta
    user_b = UserIdentity(
        id="usr_beta",
        email="owner@beta.com",
        full_name="Beta Owner",
        password_hash=AuthService.hash_password("Password123!"),
        is_active=True,
        is_verified=True,
    )
    org_b = Organization(id="org_beta", name="Beta Org", slug="beta-org")
    biz_b = Business(id="biz_beta", organization_id=org_b.id, name="Beta Primary", status="active")
    mem_b = OrganizationMembership(user_id=user_b.id, organization_id=org_b.id, role="owner")

    db_session.add_all([user_a, org_a, biz_a, mem_a, user_b, org_b, biz_b, mem_b])
    db_session.flush()

    # 3. Seed Alpha records: 2 customers, 3 sales
    cust_a1 = Customer(
        business_id=biz_a.id,
        customer_code="CUST-ALPHA-1",
        name="Alpha Customer 1",
        email="a1@alpha.com",
        city="Alpha City",
        customer_segment="Corporate",
        acquisition_date=now_utc.date(),
        created_at=now_utc,
        updated_at=now_utc,
    )
    cust_a2 = Customer(
        business_id=biz_a.id,
        customer_code="CUST-ALPHA-2",
        name="Alpha Customer 2",
        email="a2@alpha.com",
        city="Alpha City",
        customer_segment="Retail",
        acquisition_date=now_utc.date(),
        created_at=now_utc,
        updated_at=now_utc,
    )
    db_session.add_all([cust_a1, cust_a2])
    db_session.flush()

    for i in range(3):
        sale = Sale(
            business_id=biz_a.id,
            transaction_number=f"TXN-ALPHA-{i+1}",
            customer_id=cust_a1.id,
            transaction_date=now_utc,
            status="completed",
            subtotal=Decimal("100.00"),
            discount_amount=Decimal("0.00"),
            tax_amount=Decimal("8.00"),
            total_amount=Decimal("108.00"),
            created_at=now_utc,
            updated_at=now_utc,
        )
        db_session.add(sale)

    # 4. Seed Beta records: 1 customer, 1 sale
    cust_b1 = Customer(
        business_id=biz_b.id,
        customer_code="CUST-BETA-1",
        name="Beta Customer 1",
        email="b1@beta.com",
        city="Beta City",
        customer_segment="VIP",
        acquisition_date=now_utc.date(),
        created_at=now_utc,
        updated_at=now_utc,
    )
    db_session.add(cust_b1)
    db_session.flush()

    sale_b = Sale(
        business_id=biz_b.id,
        transaction_number="TXN-BETA-1",
        customer_id=cust_b1.id,
        transaction_date=now_utc,
        status="completed",
        subtotal=Decimal("500.00"),
        discount_amount=Decimal("50.00"),
        tax_amount=Decimal("36.00"),
        total_amount=Decimal("486.00"),
        created_at=now_utc,
        updated_at=now_utc,
    )
    db_session.add(sale_b)
    db_session.commit()

    token_a = AuthService.create_access_token(
        user_id=user_a.id,
        email=user_a.email,
        organization_id=org_a.id,
        business_id=biz_a.id,
    )
    token_b = AuthService.create_access_token(
        user_id=user_b.id,
        email=user_b.email,
        organization_id=org_b.id,
        business_id=biz_b.id,
    )

    return {
        "biz_a": biz_a.id,
        "biz_b": biz_b.id,
        "headers_a": {"Authorization": f"Bearer {token_a}", "X-Business-ID": biz_a.id},
        "headers_b": {"Authorization": f"Bearer {token_b}", "X-Business-ID": biz_b.id},
    }


def test_data_health_tenant_isolation(client: TestClient, two_tenants_data: dict) -> None:
    """Verify /api/v1/data/health strictly isolates total_records per tenant."""
    # Alpha has 2 customers + 3 sales = 5 records
    res_a = client.get("/api/v1/data/health", headers=two_tenants_data["headers_a"])
    assert res_a.status_code == 200
    assert res_a.json()["total_records"] == 5

    # Beta has 1 customer + 1 sale = 2 records
    res_b = client.get("/api/v1/data/health", headers=two_tenants_data["headers_b"])
    assert res_b.status_code == 200
    assert res_b.json()["total_records"] == 2


def test_data_tables_tenant_isolation(client: TestClient, two_tenants_data: dict) -> None:
    """Verify /api/v1/data/tables reports accurate row counts per tenant."""
    res_a = client.get("/api/v1/data/tables", headers=two_tenants_data["headers_a"])
    assert res_a.status_code == 200
    tables_a = {t["table_name"]: t["row_count"] for t in res_a.json()}
    assert tables_a["customers"] == 2
    assert tables_a["sales"] == 3

    res_b = client.get("/api/v1/data/tables", headers=two_tenants_data["headers_b"])
    assert res_b.status_code == 200
    tables_b = {t["table_name"]: t["row_count"] for t in res_b.json()}
    assert tables_b["customers"] == 1
    assert tables_b["sales"] == 1


def test_data_profile_tenant_isolation(client: TestClient, two_tenants_data: dict) -> None:
    """Verify /api/v1/data/profile/{dataset} isolates raw data and statistics per tenant."""
    res_a = client.get("/api/v1/data/profile/sales", headers=two_tenants_data["headers_a"])
    assert res_a.status_code == 200
    assert res_a.json()["total_rows"] == 3

    res_b = client.get("/api/v1/data/profile/sales", headers=two_tenants_data["headers_b"])
    assert res_b.status_code == 200
    assert res_b.json()["total_rows"] == 1


def test_data_quality_tenant_isolation(client: TestClient, two_tenants_data: dict) -> None:
    """Verify /api/v1/data/quality/{dataset} checks are executed strictly on tenant records."""
    res_a = client.get("/api/v1/data/quality/sales", headers=two_tenants_data["headers_a"])
    assert res_a.status_code == 200
    assert res_a.json()["dataset_name"] == "sales"
    assert res_a.json()["status"] == "PASSED"

    res_b = client.get("/api/v1/data/quality/sales", headers=two_tenants_data["headers_b"])
    assert res_b.status_code == 200
    assert res_b.json()["dataset_name"] == "sales"
    assert res_b.json()["status"] == "PASSED"


def test_data_endpoints_reject_idor(client: TestClient, two_tenants_data: dict) -> None:
    """Cross-tenant header tampering must be rejected with 403 Forbidden."""
    # User A attempting to inspect User B's business workspace
    forged_headers_a = {
        "Authorization": two_tenants_data["headers_a"]["Authorization"],
        "X-Business-ID": two_tenants_data["biz_b"],
    }
    res = client.get("/api/v1/data/health", headers=forged_headers_a)
    assert res.status_code == 403

    res = client.get("/api/v1/data/tables", headers=forged_headers_a)
    assert res.status_code == 403

    res = client.get("/api/v1/data/profile/sales", headers=forged_headers_a)
    assert res.status_code == 403

    res = client.get("/api/v1/data/quality/sales", headers=forged_headers_a)
    assert res.status_code == 403
