"""Deterministic Phase 25D.3 tests for Tenant-Aware Semantic Service & Endpoint Upgrade.

Verifies:
1. Tenant-specific custom synonyms vs global aliases.
2. Cross-tenant isolation (Tenant A custom synonyms invisible to Tenant B).
3. Confidence propagation through TenantSemanticService.
4. Ambiguous and unsupported queries reject verified provenance and assign confidence=0.0.
5. Dimension and filter validation against supported tool schemas and tenant data.
6. Temporal context and fiscal-calendar preservation (including custom fiscal year start).
7. Provenance integrity with grounded accounting rules and policy references.
8. API backward compatibility with /api/v1/semantic/resolve (with and without tenant context).
"""

from collections.abc import Generator
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from uuid import uuid4

import pytest
from app.api.deps import get_db_session
from app.core.database import get_db
from app.main import app
from app.models.base import Base
from app.models.customer import Customer
from app.models.sale import Sale
from app.services.auth_service import AuthService
from app.services.tenant_semantic_service import TenantSemanticService
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
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
def db_session() -> Generator[Session, None, None]:
    Base.metadata.create_all(bind=engine)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture(scope="module")
def client(db_session: Session) -> Generator[TestClient, None, None]:
    def override_get_db() -> Generator[Session, None, None]:
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_db_session] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture(scope="module")
def phase25d3_fixture(db_session: Session) -> dict[str, Any]:
    """Sets up two isolated businesses: Tenant A (fiscal_year_start=7) and Tenant B (fiscal_year_start=1)."""
    user_a, org_a, biz_a = AuthService.signup(
        db=db_session,
        email=f"owner_25d3_a_{uuid4().hex[:6]}@domain-a.com",
        password="SecurePassword123!",
        full_name="Alice 25D3",
        organization_name="Enterprise Alpha 25D3",
        business_name="Alpha Retail 25D3",
    )
    # Set fiscal year start to 7 (July)
    biz_a.fiscal_year_start = 7
    biz_a.timezone = "America/New_York"
    biz_a.currency = "USD"

    # Seed sales and customers for Tenant A so metrics are AVAILABLE
    cust_a = Customer(
        business_id=biz_a.id,
        customer_code="CUST-25D3-A1",
        name="Alpha Customer",
        email="cust_a@alpha.com",
        city="New York",
        customer_segment="Enterprise",
        acquisition_date=date(2025, 1, 1),
    )
    db_session.add(cust_a)
    db_session.flush()

    sale_a = Sale(
        business_id=biz_a.id,
        customer_id=cust_a.id,
        transaction_date=datetime(2025, 2, 1, 12, 0, tzinfo=UTC),
        subtotal=Decimal("1200.00"),
        total_amount=Decimal("1200.00"),
        transaction_number=f"TX-{uuid4().hex[:8]}",
    )
    db_session.add(sale_a)
    db_session.commit()

    token_a = AuthService.create_access_token(
        user_id=user_a.id,
        email=user_a.email,
        organization_id=org_a.id,
        business_id=biz_a.id,
    )

    # Activate semantic model for Tenant A with custom synonyms
    model_a = TenantSemanticService.generate_business_understanding(
        business_id=biz_a.id,
        organization_id=org_a.id,
        db=db_session,
        custom_synonyms={
            "alpha_topline": "net_revenue",
            "contract_sales": "net_revenue",
        },
    )

    # Setup Tenant B (standard fiscal year start 1)
    user_b, org_b, biz_b = AuthService.signup(
        db=db_session,
        email=f"owner_25d3_b_{uuid4().hex[:6]}@domain-b.com",
        password="SecurePassword123!",
        full_name="Bob 25D3",
        organization_name="Enterprise Beta 25D3",
        business_name="Beta Retail 25D3",
    )
    token_b = AuthService.create_access_token(
        user_id=user_b.id,
        email=user_b.email,
        organization_id=org_b.id,
        business_id=biz_b.id,
    )

    # Activate semantic model for Tenant B with different custom synonyms
    model_b = TenantSemanticService.generate_business_understanding(
        business_id=biz_b.id,
        organization_id=org_b.id,
        db=db_session,
        custom_synonyms={
            "beta_intake": "net_revenue",
        },
    )

    return {
        "user_a": user_a,
        "biz_a": biz_a,
        "token_a": token_a,
        "model_a": model_a,
        "user_b": user_b,
        "biz_b": biz_b,
        "token_b": token_b,
        "model_b": model_b,
    }


def test_tenant_specific_synonyms_and_global_aliases(
    db_session: Session, phase25d3_fixture: dict[str, Any]
) -> None:
    """1. Tenant A custom synonym resolves to net_revenue, as do global aliases."""
    biz_a = phase25d3_fixture["biz_a"]

    # Tenant-specific custom synonym
    res_custom = TenantSemanticService.resolve_query_with_tenant_context(
        query="What is our alpha_topline?",
        business_id=biz_a.id,
        db=db_session,
    )
    assert res_custom.canonical_name == "net_revenue"
    assert res_custom.matched_synonym == "alpha_topline"
    assert res_custom.confidence == 0.95
    assert res_custom.availability_status == "AVAILABLE"

    # Global alias (net sales)
    res_global = TenantSemanticService.resolve_query_with_tenant_context(
        query="What are our net sales?",
        business_id=biz_a.id,
        db=db_session,
    )
    assert res_global.canonical_name == "net_revenue"
    assert res_global.confidence == 0.95


def test_cross_tenant_isolation(
    db_session: Session, phase25d3_fixture: dict[str, Any]
) -> None:
    """2. Tenant A's custom synonym cannot resolve or leak into Tenant B's resolution."""
    biz_b = phase25d3_fixture["biz_b"]

    # Tenant B queries Tenant A's custom synonym
    res = TenantSemanticService.resolve_query_with_tenant_context(
        query="What is our alpha_topline?",
        business_id=biz_b.id,
        db=db_session,
    )
    # Must NOT resolve via Tenant A's custom synonym
    assert res.matched_synonym != "alpha_topline"
    assert res.canonical_name is None
    assert res.confidence == 0.0

    # Tenant B queries Tenant B's own custom synonym
    res_b = TenantSemanticService.resolve_query_with_tenant_context(
        query="What is our beta_intake?",
        business_id=biz_b.id,
        db=db_session,
    )
    assert res_b.canonical_name == "net_revenue"
    assert res_b.matched_synonym == "beta_intake"


def test_confidence_propagation_through_service(
    db_session: Session, phase25d3_fixture: dict[str, Any]
) -> None:
    """3. Verify strict confidence scoring rules across resolution states."""
    biz_a = phase25d3_fixture["biz_a"]

    # Exact canonical match -> 1.0
    res_exact = TenantSemanticService.resolve_query_with_tenant_context(
        query="net_revenue",
        business_id=biz_a.id,
        db=db_session,
    )
    assert res_exact.confidence == 1.0

    # Exact display name -> 1.0
    res_display = TenantSemanticService.resolve_query_with_tenant_context(
        query="Net Revenue",
        business_id=biz_a.id,
        db=db_session,
    )
    assert res_display.confidence == 1.0

    # Synonym match -> 0.95
    res_syn = TenantSemanticService.resolve_query_with_tenant_context(
        query="What is our revenue?",
        business_id=biz_a.id,
        db=db_session,
    )
    assert res_syn.confidence == 0.95

    # Ambiguous query -> 0.0
    res_ambig = TenantSemanticService.resolve_query_with_tenant_context(
        query="Show profit",
        business_id=biz_a.id,
        db=db_session,
    )
    assert res_ambig.confidence == 0.0

    # Unsupported query -> 0.0
    res_unsupp = TenantSemanticService.resolve_query_with_tenant_context(
        query="Predict customer churn",
        business_id=biz_a.id,
        db=db_session,
    )
    assert res_unsupp.confidence == 0.0


def test_ambiguous_and_unsupported_queries_provenance_safety(
    db_session: Session, phase25d3_fixture: dict[str, Any]
) -> None:
    """4. Ambiguous and unsupported queries must not claim verified lineage or provenance."""
    biz_a = phase25d3_fixture["biz_a"]

    # Ambiguous query: "margin"
    res_ambig = TenantSemanticService.resolve_query_with_tenant_context(
        query="What is our margin?",
        business_id=biz_a.id,
        db=db_session,
    )
    assert res_ambig.is_ambiguous is True
    assert res_ambig.clarification_prompt is not None
    assert len(res_ambig.ambiguity_candidates) > 0
    assert res_ambig.evidence_provenance == {}
    assert res_ambig.availability_status == "UNAVAILABLE"

    # Unsupported query: "CLV"
    res_unsupp = TenantSemanticService.resolve_query_with_tenant_context(
        query="What is our CLV?",
        business_id=biz_a.id,
        db=db_session,
    )
    assert res_unsupp.is_supported is False
    assert "CLV" in res_unsupp.unsupported_message
    assert res_unsupp.evidence_provenance == {}
    assert res_unsupp.confidence == 0.0


def test_dimension_and_filter_validation(
    db_session: Session, phase25d3_fixture: dict[str, Any]
) -> None:
    """5. Valid dimensions/filters are extracted; unsupported dimensions are stripped."""
    biz_a = phase25d3_fixture["biz_a"]

    # Supported dimension and filter: "category" and "warehouse" for stock_value
    res_valid = TenantSemanticService.resolve_query_with_tenant_context(
        query="stock value for Main Warehouse by category",
        business_id=biz_a.id,
        db=db_session,
    )
    assert res_valid.canonical_name == "stock_value"
    assert "category" in res_valid.resolved_dimensions
    assert res_valid.extracted_filters.get("warehouse") == "Main Warehouse"
    assert res_valid.confidence == 1.0

    # Unsupported filter key: net_revenue does not accept warehouse filter in get_financial_summary
    res_rev_filter = TenantSemanticService.resolve_query_with_tenant_context(
        query="revenue for Main Warehouse",
        business_id=biz_a.id,
        db=db_session,
    )
    assert res_rev_filter.extracted_filters.get("warehouse") is None
    assert "warehouse" in res_rev_filter.unsupported_filters
    assert res_rev_filter.unsupported_message is not None
    assert "warehouse" in res_rev_filter.unsupported_message

    # Unsupported dimension: inventory_turnover does not support customer_segment
    res_inv = TenantSemanticService.resolve_query_with_tenant_context(
        query="inventory turnover by customer segment",
        business_id=biz_a.id,
        db=db_session,
    )
    # customer_segment is unsupported for inventory turnover, so it must not be in resolved_dimensions
    assert "customer_segment" not in res_inv.resolved_dimensions
    assert "customer_segment" in res_inv.unsupported_dimensions
    assert res_inv.unsupported_message is not None
    assert "customer_segment" in res_inv.unsupported_message
    assert res_inv.confidence == 0.80  # Capped due to unsupported dimension request


def test_temporal_context_and_fiscal_calendar_preservation(
    db_session: Session, phase25d3_fixture: dict[str, Any]
) -> None:
    """6. Fiscal calendar start (July=7) is preserved and populated in temporal context."""
    biz_a = phase25d3_fixture["biz_a"]

    res = TenantSemanticService.resolve_query_with_tenant_context(
        query="revenue this fiscal year",
        business_id=biz_a.id,
        db=db_session,
    )
    assert res.canonical_name == "net_revenue"
    assert res.temporal_context is not None
    fc = res.temporal_context.get("fiscal_calendar")
    assert fc is not None
    assert fc["fiscal_year_start_month"] == 7
    assert fc["timezone"] == "America/New_York"
    assert fc["currency"] == "USD"
    # Starting date should be July 1
    assert "-07-01" in str(res.temporal_context.get("date_from"))
    assert res.extracted_filters.get("date_from") is not None

    # Regression verification: Non-January fiscal year (July start) in second calendar year of cycle (e.g. March 15)
    from datetime import date
    from app.agents.tools.date_interpreter import DateInterpreter
    parsed_mid_fy = DateInterpreter.interpret(
        "this fiscal year", reference_date=date(2026, 3, 15), fiscal_year_start=7
    )
    assert parsed_mid_fy["date_from"] == "2025-07-01"
    assert parsed_mid_fy["date_to"] == "2026-03-15"
    assert parsed_mid_fy["comparison_date_from"] == "2024-07-01"
    assert parsed_mid_fy["comparison_date_to"] == "2025-03-15"
    assert parsed_mid_fy["comparison_date_to"] > parsed_mid_fy["comparison_date_from"]

    # Inclusivity check: January start month-end inclusivity (October 31 should compare to October 31)
    parsed_jan_eom = DateInterpreter.interpret(
        "this fiscal year", reference_date=date(2026, 10, 31), fiscal_year_start=1
    )
    assert parsed_jan_eom["date_from"] == "2026-01-01"
    assert parsed_jan_eom["date_to"] == "2026-10-31"
    assert parsed_jan_eom["comparison_date_from"] == "2025-01-01"
    assert parsed_jan_eom["comparison_date_to"] == "2025-10-31"


def test_provenance_grounding_with_accounting_rules(
    db_session: Session, phase25d3_fixture: dict[str, Any]
) -> None:
    """7. Provenance contains grounded accounting rule ID and policy references."""
    biz_a = phase25d3_fixture["biz_a"]

    res = TenantSemanticService.resolve_query_with_tenant_context(
        query="revenue",
        business_id=biz_a.id,
        db=db_session,
    )
    prov = res.evidence_provenance
    assert prov.get("tenant_scoped") is True
    assert prov.get("source_data") == "sales"
    assert prov.get("accounting_rule_id") == "REV-001"
    assert "POL-REV-01" in prov.get("policy_reference") or "METRIC_DEFINITIONS" in prov.get("policy_reference")
    assert prov.get("rule_name") == "Net Revenue Determination"


def test_api_backward_compatibility_with_tenant_headers(
    client: TestClient, phase25d3_fixture: dict[str, Any]
) -> None:
    """8. POST /api/v1/semantic/resolve returns full 25D schema with and without tenant context."""
    biz_a = phase25d3_fixture["biz_a"]
    token_a = phase25d3_fixture["token_a"]

    # With X-Business-ID header and authentication
    resp_tenant = client.post(
        "/api/v1/semantic/resolve",
        json={"query": "alpha_topline by category"},
        headers={
            "Authorization": f"Bearer {token_a}",
            "X-Business-ID": biz_a.id,
        },
    )
    assert resp_tenant.status_code == 200
    data_t = resp_tenant.json()
    assert data_t["canonical_name"] == "net_revenue"
    assert data_t["confidence"] == 0.95
    assert "category" in data_t["resolved_dimensions"]
    assert "supported_dimensions" in data_t
    assert data_t["evidence_provenance"].get("accounting_rule_id") == "REV-001"

    # Without tenant context (pure fallback)
    resp_anon = client.post(
        "/api/v1/semantic/resolve",
        json={"query": "net revenue by product"},
    )
    assert resp_anon.status_code == 200
    data_a = resp_anon.json()
    assert data_a["canonical_name"] == "net_revenue"
    assert "product" in data_a["resolved_dimensions"]
    assert "confidence" in data_a
    assert data_a["confidence"] == 1.0
