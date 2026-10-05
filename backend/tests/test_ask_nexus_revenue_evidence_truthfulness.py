"""Regression test suite for Ask NEXUS Revenue evidence truthfulness.

Verifies:
1. Ask NEXUS revenue evidence lists 'sales' as the only contributing source table.
2. 'sale_items', 'products', and 'expenses' are not falsely listed as contributing sources,
   but are explicitly labeled as supporting / data-availability probes.
3. Canonical semantic Net Revenue formula matches the executed formula:
   SUM(sales.subtotal - sales.discount_amount) and SUM(subtotal - discount_amount).
4. Tenant predicate (business_id) is present and disclosed in source_columns and filters.
5. Existing revenue calculation accurately computes ₹254,192 / 60 orders,
   preserves missing COGS as incomplete (no fabricated values), and enforces tenant isolation.
"""

from datetime import date, datetime, timezone
from decimal import Decimal
import pytest
from sqlalchemy.orm import Session

from app.analytics.core.context import AnalysisContext
from app.analytics.service import AnalyticsService
from app.agents.service import NexusAgentService
from app.models.customer import Customer
from app.models.sale import Sale
from app.models.tenant import Business, Organization, OrganizationMembership, UserIdentity
from app.services.tenant_semantic_service import TenantSemanticService


def _seed_revenue_tenant(
    db: Session,
    suffix: str = "rev_truth",
    order_count: int = 60,
    target_total: Decimal = Decimal("254192.00"),
) -> tuple[Organization, Business, UserIdentity]:
    """Helper to seed a tenant with exactly order_count completed sales totaling target_total."""
    org = Organization(
        id=f"org_{suffix}",
        name=f"Org {suffix}",
        slug=f"org-{suffix}",
    )
    user = UserIdentity(
        id=f"usr_{suffix}",
        email=f"{suffix}@nexus.test",
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
        id=f"biz_{suffix}",
        organization_id=org.id,
        name=f"Business {suffix}",
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
        customer_code=f"CUST-{suffix}",
        name=f"Customer {suffix}",
        email=f"cust_{suffix}@test.com",
        city="Mumbai",
        customer_segment="Retail",
        acquisition_date=date(2024, 1, 1),
    )
    db.add(cust)
    db.flush()

    if order_count > 0:
        base_val = (target_total / order_count).quantize(Decimal("0.01"))
        remainder = target_total - (base_val * (order_count - 1))

        sales = []
        for i in range(order_count):
            amount = remainder if i == order_count - 1 else base_val
            discount = Decimal("10.00")
            subtotal = amount + discount

            sale = Sale(
                business_id=biz.id,
                transaction_number=f"TXN-{suffix}-{i:03d}",
                customer_id=cust.id,
                transaction_date=datetime(2024, 8, 1 + (i % 28), 12, 0, tzinfo=timezone.utc),
                subtotal=subtotal,
                discount_amount=discount,
                total_amount=amount,
                status="completed",
                tax_amount=Decimal("0.00"),
            )
            sales.append(sale)

        db.add_all(sales)

    db.commit()

    TenantSemanticService.generate_business_understanding(
        business_id=biz.id,
        organization_id=biz.organization_id,
        db=db,
    )
    return org, biz, user


def test_analytics_service_revenue_evidence_truthfulness(db_session: Session):
    """Verify AnalyticsService evidence lists only sales as contributing source and discloses tenant predicate."""
    org, biz, user = _seed_revenue_tenant(db_session, suffix="truth_srv")

    service = AnalyticsService(db_session)
    context = AnalysisContext(
        business_id=biz.id,
    )

    summary, ev = service.get_financial_summary(context)

    # 1. Calculation correctness
    assert summary.net_sales.value == Decimal("254192.00")
    assert summary.orders.value == 60
    assert summary.cogs.value is None
    assert summary.cogs.formatted == "Incomplete"
    assert summary.gross_profit.value is None
    assert summary.gross_profit.formatted == "Incomplete"

    # 2. Evidence provenance
    assert ev is not None
    # Only sales is the contributing source
    assert ev.source_tables == ["sales"]
    assert "sale_items" not in ev.source_tables
    assert "products" not in ev.source_tables
    assert "expenses" not in ev.source_tables

    # Data availability probes are separated
    assert "sale_items" in ev.supporting_sources
    assert "products" in ev.supporting_sources
    assert "expenses" in ev.supporting_sources

    # Columns contain subtotal, discount_amount, id, status, business_id
    for expected_col in ["subtotal", "discount_amount", "id", "status", "business_id"]:
        assert expected_col in ev.source_columns

    # Formula matches actual calculation
    assert ev.calculation == "SUM(sales.subtotal - sales.discount_amount)"
    assert ev.mathematical_formula == "SUM(subtotal - discount_amount)"

    # Tenant predicate is disclosed in filters
    assert ev.filters.get("business_id") == biz.id


def test_tenant_semantic_definition_alignment(db_session: Session):
    """Verify TenantSemanticService canonical Net Revenue matches the actual SUM(subtotal - discount_amount)."""
    org, biz, user = _seed_revenue_tenant(db_session, suffix="truth_sem")

    res = TenantSemanticService.resolve_query_with_tenant_context(
        query="What is our net revenue?",
        business_id=biz.id,
        db=db_session,
    )

    assert res.canonical_name == "net_revenue"
    assert res.source_table == "sales"
    assert res.source_field == "subtotal - discount_amount"
    assert res.calculation_formula == "SUM(sales.subtotal - sales.discount_amount)"
    assert res.evidence_provenance["tenant_scoped"] is True
    assert res.evidence_provenance["calculation"] == "SUM(sales.subtotal - sales.discount_amount)"
    assert res.evidence_provenance["semantic_definition"] == "sales.subtotal - discount_amount"


def test_ask_nexus_agent_revenue_evidence_and_isolation(db_session: Session):
    """Verify Ask NEXUS agent response returns truthful evidence, ₹254,192 / 60 orders, and enforces tenant isolation."""
    org_a, biz_a, user_a = _seed_revenue_tenant(db_session, suffix="truth_agt_a")
    org_b, biz_b, user_b = _seed_revenue_tenant(db_session, suffix="truth_agt_b", order_count=0, target_total=Decimal("0.00"))
    org_c, biz_c, user_c = _seed_revenue_tenant(db_session, suffix="truth_agt_c", order_count=5, target_total=Decimal("5000.00"))

    agent_service = NexusAgentService(db_session)

    # 1. Run for Tenant A (60 orders, ₹254,192.00)
    res_a = agent_service.run_analysis(
        query="What is our net revenue and how many orders do we have?",
        explanation_level="manager",
        organization_id=biz_a.organization_id,
        business_id=biz_a.id,
        user_id=user_a.id,
        enforce_readiness=False,
    )

    assert res_a.status == "completed"
    assert len(res_a.evidence) > 0
    ev_a = res_a.evidence[0]

    # Provenance truthfulness
    assert ev_a.source_tables == ["sales"]
    assert "sale_items" not in ev_a.source_tables
    assert "products" not in ev_a.source_tables
    assert "expenses" not in ev_a.source_tables
    assert "sale_items" in ev_a.supporting_sources
    assert "products" in ev_a.supporting_sources
    assert "expenses" in ev_a.supporting_sources

    assert ev_a.calculation == "SUM(sales.subtotal - sales.discount_amount)"
    assert ev_a.mathematical_formula == "SUM(subtotal - discount_amount)"
    assert "business_id" in ev_a.source_columns
    assert ev_a.filters.get("business_id") == biz_a.id

    # Numerical result truthfulness
    assert ev_a.result_summary["net_sales"] == 254192.0
    assert ev_a.result_summary["orders"] == 60
    assert ev_a.row_count == 60

    # Semantic context alignment
    assert res_a.semantic_context is not None
    assert res_a.semantic_context["canonical_name"] == "net_revenue"
    assert res_a.semantic_context["calculation_formula"] == "SUM(sales.subtotal - sales.discount_amount)"
    assert res_a.semantic_context["source_field"] == "subtotal - discount_amount"

    # 2. Run for Tenant B (0 orders -> cleanly unsupported without bleeding Tenant A data)
    res_b = agent_service.run_analysis(
        query="What is our net revenue and how many orders do we have?",
        explanation_level="manager",
        organization_id=biz_b.organization_id,
        business_id=biz_b.id,
        user_id=user_b.id,
        enforce_readiness=False,
    )
    assert res_b.status == "unsupported"
    assert len(res_b.evidence) == 0

    # 3. Run for Tenant C (5 orders, ₹5,000 -> isolated to Tenant C only)
    res_c = agent_service.run_analysis(
        query="What is our net revenue and how many orders do we have?",
        explanation_level="manager",
        organization_id=biz_c.organization_id,
        business_id=biz_c.id,
        user_id=user_c.id,
        enforce_readiness=False,
    )
    assert res_c.status == "completed"
    assert len(res_c.evidence) > 0
    ev_c = res_c.evidence[0]
    assert ev_c.filters.get("business_id") == biz_c.id
    assert ev_c.result_summary["net_sales"] == 5000.0
    assert ev_c.result_summary["orders"] == 5
    assert ev_c.row_count == 5
