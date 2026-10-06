"""Regression tests for Targeted Acceptance Test 2.

Covers:
1. Customer Segmentation API contract (dimension_value, metric_value, order_count).
2. Revenue time-series order-level fallback when line items are missing, preserving tenant isolation.
3. Profit time-series refuses to invent points when product costs are missing.
4. Product rankings return empty without hallucinating when no product data exists.
"""

from datetime import datetime, timezone
from decimal import Decimal
import pytest
from sqlalchemy.orm import Session
from app.models.tenant import Business, Organization
from app.models.customer import Customer
from app.models.sale import Sale
from app.analytics.core.types import PeriodGranularity
from app.analytics.core.context import AnalysisContext
from app.analytics.core.models import BreakdownItem, BreakdownResult
from app.analytics.descriptive.time_series import TimeSeriesAnalyzer
from app.analytics.descriptive.segmentation import SegmentationAnalyzer
from app.analytics.service import AnalyticsService


@pytest.fixture
def sales_only_tenant_db(db_session: Session):
    """Seed tenant A with order-only sales (no SaleItem, no Product) and tenant B with separate sales."""
    org_a = Organization(id="org-acceptance-a", name="Acceptance Org A", slug="acceptance-org-a")
    org_b = Organization(id="org-acceptance-b", name="Acceptance Org B", slug="acceptance-org-b")
    db_session.add_all([org_a, org_b])
    db_session.flush()

    # Tenant A
    biz_a = Business(
        id="biz-acceptance-a",
        organization_id="org-acceptance-a",
        name="Acceptance Tenant A",
        industry="Retail",
        country="India",
        currency="INR",
        timezone="UTC",
    )
    # Tenant B
    biz_b = Business(
        id="biz-acceptance-b",
        organization_id="org-acceptance-b",
        name="Acceptance Tenant B",
        industry="Retail",
        country="India",
        currency="INR",
        timezone="UTC",
    )
    db_session.add_all([biz_a, biz_b])
    db_session.flush()

    cust_a = Customer(
        id=9001,
        business_id="biz-acceptance-a",
        customer_code="CUST-ACC-01",
        name="Retail Cust A",
        email="cust_a@example.com",
        customer_segment="Retail",
        city="Mumbai",
        acquisition_date=datetime(2025, 1, 1, tzinfo=timezone.utc).date(),
    )
    cust_b = Customer(
        id=9002,
        business_id="biz-acceptance-b",
        customer_code="CUST-ACC-02",
        name="Wholesale Cust B",
        email="cust_b@example.com",
        customer_segment="Wholesale",
        city="Delhi",
        acquisition_date=datetime(2025, 1, 1, tzinfo=timezone.utc).date(),
    )
    db_session.add_all([cust_a, cust_b])
    db_session.flush()

    # Tenant A: 3 sales across 2 months (Jan 2026, Feb 2026)
    sale_a1 = Sale(
        id=9101,
        business_id="biz-acceptance-a",
        transaction_number="TX-A-01",
        customer_id=9001,
        transaction_date=datetime(2026, 1, 15, 12, 0, tzinfo=timezone.utc),
        status="completed",
        subtotal=Decimal("1000.00"),
        discount_amount=Decimal("100.00"),
        tax_amount=Decimal("0.00"),
        total_amount=Decimal("900.00"),
    )
    sale_a2 = Sale(
        id=9102,
        business_id="biz-acceptance-a",
        transaction_number="TX-A-02",
        customer_id=9001,
        transaction_date=datetime(2026, 1, 20, 12, 0, tzinfo=timezone.utc),
        status="completed",
        subtotal=Decimal("2000.00"),
        discount_amount=Decimal("0.00"),
        tax_amount=Decimal("0.00"),
        total_amount=Decimal("2000.00"),
    )
    sale_a3 = Sale(
        id=9103,
        business_id="biz-acceptance-a",
        transaction_number="TX-A-03",
        customer_id=9001,
        transaction_date=datetime(2026, 2, 10, 12, 0, tzinfo=timezone.utc),
        status="completed",
        subtotal=Decimal("1500.00"),
        discount_amount=Decimal("0.00"),
        tax_amount=Decimal("0.00"),
        total_amount=Decimal("1500.00"),
    )

    # Tenant B: sale with 10,000 revenue (must NEVER leak into Tenant A)
    sale_b = Sale(
        id=9104,
        business_id="biz-acceptance-b",
        transaction_number="TX-B-01",
        customer_id=9002,
        transaction_date=datetime(2026, 1, 18, 12, 0, tzinfo=timezone.utc),
        status="completed",
        subtotal=Decimal("10000.00"),
        discount_amount=Decimal("0.00"),
        tax_amount=Decimal("0.00"),
        total_amount=Decimal("10000.00"),
    )
    db_session.add_all([sale_a1, sale_a2, sale_a3, sale_b])
    db_session.commit()
    return db_session


def test_customer_segmentation_contract_and_values(sales_only_tenant_db: Session):
    """Test 1: Verify BreakdownItem exposes dimension_value, metric_value, order_count matching real data."""
    ctx = AnalysisContext(business_id="biz-acceptance-a")
    breakdown = SegmentationAnalyzer.get_customer_segment_breakdown(sales_only_tenant_db, ctx)

    assert len(breakdown.items) == 1
    item = breakdown.items[0]

    # Verify standard and compatibility fields
    assert item.key == "Retail"
    assert item.label == "Retail"
    assert item.dimension_value == "Retail"
    assert item.value == Decimal("4400.00")  # (1000-100) + 2000 + 1500 = 4400
    assert item.metric_value == Decimal("4400.00")
    assert item.count == 3
    assert item.order_count == 3
    assert item.percentage_of_total == 100.0

    # Ensure Tenant B Wholesale segment was NOT included
    assert "Wholesale" not in [i.key for i in breakdown.items]


def test_revenue_timeseries_order_level_fallback(sales_only_tenant_db: Session):
    """Test 2: Verify monthly revenue telemetry aggregates from order headers when line items are missing."""
    ctx = AnalysisContext(
        business_id="biz-acceptance-a",
        granularity=PeriodGranularity.MONTHLY,
    )
    result = TimeSeriesAnalyzer.evaluate(sales_only_tenant_db, ctx, metric="revenue")

    assert result.is_order_level_fallback is True
    assert len(result.points) == 2

    # Jan 2026: 2 orders, (900 + 2000) = 2900
    jan = result.points[0]
    assert jan.period_label == "2026-01"
    assert jan.value == Decimal("2900.00")
    assert jan.orders == 2

    # Feb 2026: 1 order, 1500
    feb = result.points[1]
    assert feb.period_label == "2026-02"
    assert feb.value == Decimal("1500.00")
    assert feb.orders == 1

    assert result.total == Decimal("4400.00")
    # Verify Tenant B's 10,000 revenue was completely isolated
    assert result.total != Decimal("14400.00")


def test_timeseries_evidence_discloses_order_level_fallback(sales_only_tenant_db: Session):
    """Test 3: Evidence metadata correctly reflects order-level aggregation fallback."""
    ctx = AnalysisContext(
        business_id="biz-acceptance-a",
        granularity=PeriodGranularity.MONTHLY,
    )
    service = AnalyticsService(sales_only_tenant_db, business_id="biz-acceptance-a")
    _, evidence = service.get_timeseries_analytics(ctx, metric="revenue")

    assert evidence.source_tables == ["sales"]
    assert "transaction_date" in evidence.source_columns
    assert "subtotal" in evidence.source_columns
    assert "order-level aggregation fallback" in evidence.calculation
    assert len(evidence.assumptions) > 0


def test_profit_timeseries_refuses_to_invent_points_without_costs(sales_only_tenant_db: Session):
    """Test 4: When product cost data is missing, profit telemetry returns empty points rather than inventing COGS."""
    ctx = AnalysisContext(
        business_id="biz-acceptance-a",
        granularity=PeriodGranularity.MONTHLY,
    )
    result = TimeSeriesAnalyzer.evaluate(sales_only_tenant_db, ctx, metric="profit")

    # Profit requires line items and catalog unit costs; should not invent points
    assert len(result.points) == 0
    assert result.total == Decimal("0.00")


def test_product_leaderboard_empty_when_no_catalog_data(sales_only_tenant_db: Session):
    """Test 5: Product rankings return an empty list without hallucinations when products table has no data."""
    ctx = AnalysisContext(business_id="biz-acceptance-a")
    service = AnalyticsService(sales_only_tenant_db, business_id="biz-acceptance-a")
    rankings, evidence = service.get_product_rankings(ctx, ranking_metric="revenue")

    assert rankings == []
    assert evidence.result_summary["items_returned"] == 0
