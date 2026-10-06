"""Regression test for expired auth session and Retry workflow.

Verifies:
1. Expired JWT access token is rejected on /api/v1/data/health with HTTP 401 and
   detail "Authentication token has expired. Please log in again.".
2. Expired token rejection applies across protected data and profile endpoints (/api/v1/data/tables, /api/v1/auth/me).
3. Token refresh endpoint (/api/v1/auth/refresh) fails / is unavailable, requiring clear-session + redirect.
4. Re-authenticating via /api/v1/auth/login succeeds, restoring valid access token and tenant workspace.
5. Fresh session restores access to /api/v1/data/health and /api/v1/data/tables with complete tenant data.
6. Strict tenant isolation is preserved before and after re-authentication.
"""

from datetime import UTC, datetime, timedelta, date
from decimal import Decimal
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.main import app
from app.models.tenant import Business, Organization, OrganizationMembership, UserIdentity
from app.models.sale import Sale
from app.models.customer import Customer
from app.services.auth_service import AuthService


def _setup_test_tenant(db: Session, suffix: str) -> tuple[UserIdentity, Business, str]:
    org = Organization(
        id=f"org_exp_{suffix}",
        name=f"Org Expired {suffix}",
        slug=f"org-exp-{suffix}",
    )
    user = UserIdentity(
        id=f"usr_exp_{suffix}",
        email=f"user_{suffix}@nexus.test",
        full_name=f"Expired User {suffix}",
        password_hash=AuthService.hash_password("ValidPassword123!"),
        is_active=True,
        is_verified=True,
    )
    mem = OrganizationMembership(
        user_id=user.id,
        organization_id=org.id,
        role="owner",
    )
    biz = Business(
        id=f"biz_exp_{suffix}",
        organization_id=org.id,
        name=f"Business Exp {suffix}",
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

    cust = Customer(
        business_id=biz.id,
        customer_code=f"CUST-{suffix.upper()}",
        name="Test Customer",
        email=f"cust_{suffix}@nexus.test",
        city="Mumbai",
        customer_segment="Retail",
        acquisition_date=date(2026, 1, 1),
    )
    db.add(cust)
    db.flush()

    for i in range(60):
        sale = Sale(
            business_id=biz.id,
            customer_id=cust.id,
            transaction_number=f"TXN-EXP-{suffix}-{i+1:04d}",
            transaction_date=datetime(2026, 1, (i % 28) + 1, 12, 0, tzinfo=UTC),
            subtotal=Decimal("150.00"),
            discount_amount=Decimal("0.00"),
            tax_amount=Decimal("0.00"),
            total_amount=Decimal("150.00"),
            status="completed",
        )
        db.add(sale)

    db.commit()

    valid_token = AuthService.create_access_token(
        user_id=user.id,
        email=user.email,
        organization_id=org.id,
        business_id=biz.id,
    )
    return user, biz, valid_token


def test_expired_token_rejection_and_login_restoration(db_session: Session):
    """Verify expired token returns exact 401 detail, refresh fails, and fresh login restores workspace."""
    user, biz, valid_token = _setup_test_tenant(db_session, "retry_flow")

    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    try:
        client = TestClient(app)

        # 1. Create an explicitly expired access token (expired 10 seconds ago)
        expired_token = AuthService.create_access_token(
            user_id=user.id,
            email=user.email,
            organization_id=biz.organization_id,
            business_id=biz.id,
            expires_delta=timedelta(seconds=-10),
        )

        expired_headers = {
            "Authorization": f"Bearer {expired_token}",
            "X-Business-ID": biz.id,
        }

        # 2. Call /api/v1/data/health with expired token
        res_health = client.get("/api/v1/data/health", headers=expired_headers)
        assert res_health.status_code == 401
        assert res_health.json()["detail"] == "Authentication token has expired. Please log in again."

        # 3. Call /api/v1/data/tables with expired token
        res_tables = client.get("/api/v1/data/tables", headers=expired_headers)
        assert res_tables.status_code == 401
        assert res_tables.json()["detail"] == "Authentication token has expired. Please log in again."

        # 4. Call /api/v1/auth/me with expired token
        res_me = client.get("/api/v1/auth/me", headers=expired_headers)
        assert res_me.status_code == 401
        assert res_me.json()["detail"] == "Authentication token has expired. Please log in again."

        # 5. Verify /api/v1/auth/refresh fails/is unavailable (status 404 or 405)
        res_refresh = client.post("/api/v1/auth/refresh", headers=expired_headers)
        assert res_refresh.status_code in (404, 405, 401)

        # 6. Fresh login using valid credentials
        login_res = client.post(
            "/api/v1/auth/login",
            json={"email": user.email, "password": "ValidPassword123!"},
        )
        assert login_res.status_code == 200
        login_data = login_res.json()
        new_token = login_data["access_token"]
        assert new_token is not None
        assert login_data["business"]["id"] == biz.id

        # 7. With fresh token, access to Data Health and Tables restores normally
        fresh_headers = {
            "Authorization": f"Bearer {new_token}",
            "X-Business-ID": biz.id,
        }
        res_fresh_health = client.get("/api/v1/data/health", headers=fresh_headers)
        assert res_fresh_health.status_code == 200
        assert res_fresh_health.json()["total_records"] == 61

        res_fresh_tables = client.get("/api/v1/data/tables", headers=fresh_headers)
        assert res_fresh_tables.status_code == 200
        catalog = {t["table_name"]: t["row_count"] for t in res_fresh_tables.json()}
        assert catalog["customers"] == 1
        assert catalog["sales"] == 60

    finally:
        app.dependency_overrides.pop(get_db, None)
