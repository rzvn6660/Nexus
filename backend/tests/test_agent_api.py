"""Tests for the agent API endpoint POST /api/v1/agent/analyze."""

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.main import app
from app.models.tenant import Business, Organization, OrganizationMembership, TenantSemanticModel, UploadedDataset, UserIdentity
from app.services.auth_service import AuthService


def _get_agent_test_headers(db: Session) -> dict[str, str]:
    user = db.execute(
        select(UserIdentity).where(UserIdentity.email == "agent_test_user@nexus.internal")
    ).scalar_one_or_none()
    if not user:
        org = Organization(id="org_agent_test", name="Agent Test Org", slug="agent-test-org")
        db.add(org)
        db.flush()

        user = UserIdentity(
            id="usr_agent_test",
            email="agent_test_user@nexus.internal",
            full_name="Agent Test User",
            password_hash="hashed_pw_test",
            is_active=True,
            is_verified=True,
        )
        db.add(user)
        db.flush()

        mem = OrganizationMembership(
            user_id=user.id,
            organization_id=org.id,
            role="owner",
        )
        db.add(mem)

        biz = Business(
            id="biz_agent_test",
            organization_id=org.id,
            name="Agent Test Business",
            status="active",
        )
        db.add(biz)
        db.flush()

        dataset = UploadedDataset(
            id="ds_agent_test",
            organization_id=org.id,
            business_id=biz.id,
            filename="sales_test.csv",
            file_type="csv",
            storage_key="uploads/agent_test.csv",
            file_size_bytes=1024,
            row_count=100,
            column_count=5,
            content_hash="agent_test_hash",
            readiness_status="ready",
        )
        db.add(dataset)
        db.flush()

        sem = TenantSemanticModel(
            id="sem_agent_test",
            organization_id=org.id,
            business_id=biz.id,
            version=1,
            status="ACTIVE",
            source_dataset_id=dataset.id,
            entities_json={"Sale": {"record_count": 100}},
            metrics_json={"net_revenue": {"status": "AVAILABLE"}},
            dimensions_json={},
            synonyms_json={},
            ambiguous_terms_json={},
            business_summary_json={"total_sales": 100},
        )
        db.add(sem)
        db.commit()
    else:
        biz = db.execute(
            select(Business).where(Business.id == "biz_agent_test")
        ).scalar_one()

    token = AuthService.create_access_token(
        user_id=user.id,
        email=user.email,
        organization_id=biz.organization_id,
        business_id=biz.id,
    )
    return {
        "Authorization": f"Bearer {token}",
        "X-Business-ID": biz.id,
    }


def test_api_agent_analyze_revenue_lookup(multi_period_db: Session) -> None:
    headers = _get_agent_test_headers(multi_period_db)

    def override_get_db():
        try:
            yield multi_period_db
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)

    try:
        payload = {
            "query": "What was our revenue in August 2024?",
            "explanation_level": "manager",
            "reference_date": "2024-09-01",
        }
        response = client.post("/api/v1/agent/analyze", json=payload, headers=headers)
        assert response.status_code == 200
        data = response.json()

        assert data["status"] == "completed"
        assert data["intent"] == "metric_lookup"
        assert "get_financial_summary" in data["tools_used"]
        assert data["evidence"][0]["source_tables"] == ["sales"]
        assert "sale_items" not in data["evidence"][0]["source_tables"]
        assert "execution_metadata" in data
        assert data["execution_metadata"]["elapsed_ms"] > 0
    finally:
        app.dependency_overrides.clear()


def test_api_agent_analyze_diagnostic_variance(multi_period_db: Session) -> None:
    headers = _get_agent_test_headers(multi_period_db)

    def override_get_db():
        try:
            yield multi_period_db
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)

    try:
        payload = {
            "query": "Why did revenue change and which product contributed most?",
            "explanation_level": "analyst",
            "reference_date": "2024-09-01",
        }
        response = client.post("/api/v1/agent/analyze", json=payload, headers=headers)
        assert response.status_code == 200
        data = response.json()

        assert data["status"] == "completed"
        assert data["intent"] == "diagnostic_analysis"
        assert "run_variance_analysis" in data["tools_used"]
        assert "Traceability & Evidence" in data["answer"]
    finally:
        app.dependency_overrides.clear()


def test_api_agent_analyze_unsupported(multi_period_db: Session) -> None:
    headers = _get_agent_test_headers(multi_period_db)

    def override_get_db():
        try:
            yield multi_period_db
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)

    try:
        payload = {
            "query": "What will the weather be like tomorrow?",
            "explanation_level": "simple",
        }
        response = client.post("/api/v1/agent/analyze", json=payload, headers=headers)
        assert response.status_code == 200
        data = response.json()

        assert data["status"] == "unsupported"
        assert data["intent"] == "unsupported"
        assert len(data["tools_used"]) == 0
    finally:
        app.dependency_overrides.clear()


def test_api_agent_analyze_explanation_levels(multi_period_db: Session) -> None:
    headers = _get_agent_test_headers(multi_period_db)

    def override_get_db():
        try:
            yield multi_period_db
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)

    try:
        for lvl in ["simple", "manager", "technical"]:
            payload = {
                "query": "What are our top products by revenue?",
                "explanation_level": lvl,
                "reference_date": "2024-09-01",
            }
            response = client.post("/api/v1/agent/analyze", json=payload, headers=headers)
            assert response.status_code == 200
            data = response.json()
            assert data["explanation_level"] == lvl
            assert len(data["answer"]) > 0
    finally:
        app.dependency_overrides.clear()


def test_api_agent_analyze_anonymous_blocked() -> None:
    """Anonymous access to /api/v1/agent/analyze must return 401 Unauthorized."""
    client = TestClient(app)
    response = client.post("/api/v1/agent/analyze", json={"query": "What is revenue?"})
    assert response.status_code == 401


def test_api_agent_analyze_sales_only_tenant_missing_costs_inr(multi_period_db: Session) -> None:
    """
    Regression test: Sales-only tenant with INR currency and 0 product costs.
    Ask NEXUS must:
    1. Report Net Revenue using '₹' instead of '$'.
    2. NOT report Gross Profit as '$0.00' or '₹0.00'.
    3. NOT report Gross Margin as '0.00%'.
    4. State explicitly that Gross Profit and Gross Margin are incomplete / unavailable.
    5. State that Net Profit is marked incomplete.
    """
    from datetime import date, datetime, timezone
    from decimal import Decimal
    from app.models.customer import Customer
    from app.models.sale import Sale

    org = Organization(id="org_inr_agent", name="INR Agent Org", slug="inr-agent-org")
    biz = Business(
        id="biz_inr_agent_sales_only",
        organization_id=org.id,
        name="INR Agent Sales Only",
        currency="INR",
        status="active",
    )
    user = UserIdentity(
        id="usr_inr_agent",
        email="inr_agent@nexus.internal",
        full_name="INR Agent User",
        password_hash="hashed_pw_test",
        is_active=True,
        is_verified=True,
    )
    mem = OrganizationMembership(
        user_id=user.id,
        organization_id=org.id,
        role="owner",
    )
    cust = Customer(
        business_id=biz.id,
        customer_code="CUST-INR-AGENT-01",
        name="INR Agent Customer",
        email="inr_cust@example.com",
        city="Bengaluru",
        customer_segment="Enterprise",
        acquisition_date=date(2024, 1, 1),
    )
    ds = UploadedDataset(
        id="ds_inr_agent_sales",
        organization_id=org.id,
        business_id=biz.id,
        filename="sales_inr.csv",
        file_type="csv",
        storage_key="uploads/inr_sales.csv",
        file_size_bytes=2048,
        row_count=50,
        column_count=5,
        content_hash="inr_agent_sales_hash",
        readiness_status="ready",
    )
    sem = TenantSemanticModel(
        id="sem_inr_agent_sales",
        organization_id=org.id,
        business_id=biz.id,
        version=1,
        status="ACTIVE",
        source_dataset_id=ds.id,
        entities_json={"Sale": {"record_count": 50}},
        metrics_json={"net_revenue": {"status": "AVAILABLE"}},
        dimensions_json={},
        synonyms_json={},
        ambiguous_terms_json={},
        business_summary_json={"total_sales": 50},
    )
    multi_period_db.add_all([org, biz, user, mem, cust, ds, sem])
    multi_period_db.flush()

    sale = Sale(
        business_id=biz.id,
        transaction_number="TXN-INR-AGENT-001",
        customer_id=cust.id,
        transaction_date=datetime(2024, 8, 15, 12, 0, tzinfo=timezone.utc),
        status="completed",
        subtotal=Decimal("5000.00"),
        discount_amount=Decimal("0.00"),
        tax_amount=Decimal("900.00"),
        total_amount=Decimal("5900.00"),
    )
    multi_period_db.add(sale)
    multi_period_db.commit()

    token = AuthService.create_access_token(
        user_id=user.id,
        email=user.email,
        organization_id=org.id,
        business_id=biz.id,
    )
    headers = {
        "Authorization": f"Bearer {token}",
        "X-Business-ID": biz.id,
    }

    def override_get_db():
        try:
            yield multi_period_db
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)

    try:
        payload = {
            "query": "What was our gross profit and gross margin in August 2024?",
            "explanation_level": "manager",
            "reference_date": "2024-09-01",
        }
        response = client.post("/api/v1/agent/analyze", json=payload, headers=headers)
        assert response.status_code == 200
        data = response.json()

        assert data["status"] == "completed"
        answer = data["answer"]

        # Must format using tenant currency symbol (₹)
        assert "₹" in answer
        assert "$" not in answer

        # Must NOT report fabricated $0.00 or ₹0.00 for profit/margin
        assert "₹0.00" not in answer
        assert "$0.00" not in answer
        assert "0.00%" not in answer

        # Must explicitly communicate missing cost / incomplete status
        assert "Gross Profit and Gross Margin are currently incomplete / unavailable" in answer
        assert "catalog product unit costs (COGS) are missing" in answer
        assert "Zero COGS is not assumed to avoid fabricated margins" in answer
        assert "Net Profit is also marked incomplete" in answer
    finally:
        app.dependency_overrides.clear()

