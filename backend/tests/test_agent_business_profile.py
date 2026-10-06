"""Focused tests for tenant-safe Business Profile Context capability in Ask NEXUS."""

from datetime import UTC, datetime
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.main import app
from app.models.tenant import Business, Organization, OrganizationMembership, TenantSemanticModel, UploadedDataset, UserIdentity
from app.services.auth_service import AuthService


def _setup_tenant(
    db: Session,
    suffix: str,
    name: str = "Test Org Primary",
    industry: str = "Retail & Distribution",
    country: str = "India",
    currency: str = "INR",
    timezone: str = "UTC",
    fiscal_year_start: int = 1,
) -> tuple[UserIdentity, Business, str]:
    org = Organization(
        id=f"org_prof_{suffix}",
        name=f"Org {suffix}",
        slug=f"org-{suffix}",
    )
    user = UserIdentity(
        id=f"usr_prof_{suffix}",
        email=f"user_{suffix}@nexus.test",
        full_name=f"User {suffix}",
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
        id=f"biz_prof_{suffix}",
        organization_id=org.id,
        name=name,
        industry=industry,
        country=country,
        currency=currency,
        timezone=timezone,
        fiscal_year_start=fiscal_year_start,
        status="active",
    )
    ds = UploadedDataset(
        id=f"ds_prof_{suffix}",
        organization_id=org.id,
        business_id=biz.id,
        filename=f"sales_{suffix}.csv",
        file_type="csv",
        storage_key=f"uploads/{suffix}.csv",
        file_size_bytes=1024,
        row_count=10,
        column_count=5,
        content_hash=f"hash_{suffix}",
        readiness_status="ready",
    )
    sem = TenantSemanticModel(
        id=f"sem_prof_{suffix}",
        organization_id=org.id,
        business_id=biz.id,
        version=1,
        status="ACTIVE",
        source_dataset_id=ds.id,
        entities_json={"Sale": {"record_count": 10}},
        metrics_json={"net_revenue": {"status": "AVAILABLE"}},
        dimensions_json={},
        synonyms_json={},
        ambiguous_terms_json={},
        business_summary_json={"total_sales": 10},
    )
    db.add_all([org, user, mem, biz, ds, sem])
    db.commit()

    token = AuthService.create_access_token(
        user_id=user.id,
        email=user.email,
        organization_id=org.id,
        business_id=biz.id,
    )
    return user, biz, token


def test_1_authenticated_tenant_receives_own_profile(db_session: Session):
    """1. Authenticated tenant receives its own verified business profile."""
    _, biz_a, token_a = _setup_tenant(
        db_session,
        suffix="tenant_a",
        name="test's Org Primary",
        industry="Retail & Distribution",
        country="India",
        currency="INR",
    )

    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)

    try:
        response = client.post(
            "/api/v1/agent/analyze",
            json={
                "query": "What is our business name, industry, country, and reporting currency?",
                "explanation_level": "manager",
            },
            headers={
                "Authorization": f"Bearer {token_a}",
                "X-Business-ID": biz_a.id,
            },
        )
        assert response.status_code == 200
        data = response.json()

        assert data["status"] == "completed"
        assert data["intent"] == "business_profile"
        assert "get_business_profile" in data["tools_used"]

        answer = data["answer"]
        assert "Verified Active Business Profile:" in answer
        assert "Business Name: test's Org Primary" in answer
        assert "Industry: Retail & Distribution" in answer
        assert "Country: India" in answer
        assert "Reporting Currency: INR" in answer
        assert "Source: Active Business Profile (database verified tenant record)." in answer

        # Check evidence record provenance
        assert len(data["evidence"]) >= 1
        ev = data["evidence"][0]
        assert ev["metric"] == "business_profile"
        assert ev["source_tables"] == ["businesses"]
        assert ev["data_quality_status"] == "verified"
    finally:
        app.dependency_overrides.clear()


def test_2_unauthenticated_request_rejected():
    """2. Unauthenticated request to /api/v1/agent/analyze is rejected with 401."""
    client = TestClient(app)
    response = client.post(
        "/api/v1/agent/analyze",
        json={"query": "What is our business name, industry, country, and reporting currency?"},
    )
    assert response.status_code == 401


def test_3_cross_tenant_access_rejected(db_session: Session):
    """3. Cross-tenant access is rejected with 403 Forbidden."""
    _, biz_a, token_a = _setup_tenant(db_session, suffix="cross_a", name="Tenant A")
    _, biz_b, _ = _setup_tenant(db_session, suffix="cross_b", name="Tenant B")

    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)

    try:
        # User A attempts to query using Tenant B's business_id
        response = client.post(
            "/api/v1/agent/analyze",
            json={"query": "What is our business name?"},
            headers={
                "Authorization": f"Bearer {token_a}",
                "X-Business-ID": biz_b.id,
            },
        )
        assert response.status_code == 403
        assert "not have permission" in response.json()["detail"].lower()
    finally:
        app.dependency_overrides.clear()


def test_4_all_six_profile_fields_returned_correctly(db_session: Session):
    """4. All six profile fields (name, industry, country, currency, timezone, fiscal year) are returned correctly."""
    _, biz, token = _setup_tenant(
        db_session,
        suffix="all_six",
        name="Acme Global Enterprise",
        industry="SaaS & Cloud Platforms",
        country="Germany",
        currency="EUR",
        timezone="Europe/Berlin",
        fiscal_year_start=4,
    )

    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)

    try:
        response = client.post(
            "/api/v1/agent/analyze",
            json={
                "query": "What is our business name, industry, country, reporting currency, timezone, and fiscal year?",
                "explanation_level": "manager",
            },
            headers={
                "Authorization": f"Bearer {token}",
                "X-Business-ID": biz.id,
            },
        )
        assert response.status_code == 200
        data = response.json()
        answer = data["answer"]

        assert "Business Name: Acme Global Enterprise" in answer
        assert "Industry: SaaS & Cloud Platforms" in answer
        assert "Country: Germany" in answer
        assert "Reporting Currency: EUR" in answer
        assert "Timezone: Europe/Berlin" in answer
        assert "Fiscal Year Start: April (Month 4)" in answer
    finally:
        app.dependency_overrides.clear()


def test_5_unrelated_unsupported_queries_remain_unsupported(db_session: Session):
    """5. Unrelated unsupported queries (poems, jokes, weather) remain strictly UNSUPPORTED."""
    _, biz, token = _setup_tenant(db_session, suffix="unsupported_guard")

    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)

    try:
        unsupported_prompts = [
            "Can you write a poem about sales?",
            "Tell me a joke about finance.",
            "What will the weather be like tomorrow?",
        ]
        for prompt in unsupported_prompts:
            response = client.post(
                "/api/v1/agent/analyze",
                json={"query": prompt},
                headers={
                    "Authorization": f"Bearer {token}",
                    "X-Business-ID": biz.id,
                },
            )
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "unsupported"
            assert data["intent"] == "unsupported"
            assert "outside the current analytical engine boundary" in data["answer"]
    finally:
        app.dependency_overrides.clear()
