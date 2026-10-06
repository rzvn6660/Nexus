"""Tests for deterministic financial metrics and period-over-period comparison calculations."""

from datetime import datetime, timezone, date
from decimal import Decimal
import pytest
from sqlalchemy.orm import Session
from app.models.customer import Customer
from app.models.product import Product
from app.models.sale import Sale
from app.models.sale_item import SaleItem
from app.models.expense import Expense
from app.models.inventory import Inventory
from app.analytics.core.types import PeriodGranularity, TrendDirection, MetricUnit
from app.analytics.core.context import AnalysisContext
from app.analytics.metrics.financial import (
    FinancialMetricsCalculator,
    calculate_comparison,
)
from app.analytics.service import AnalyticsService



def test_financial_summary_single_period(multi_period_db: Session):
    """Verify single-period GAAP financial metric calculations against manual arithmetic."""
    context = AnalysisContext(
        date_from=datetime(2023, 5, 1, tzinfo=timezone.utc),
        date_to=datetime(2023, 5, 31, 23, 59, 59, tzinfo=timezone.utc),
    )
    summary = FinancialMetricsCalculator.evaluate_summary(multi_period_db, context)

    # Expected May numbers:
    # Gross Sales = 70.00 + 90.00 = 160.00
    # Discounts = 5.00
    # Net Sales = 155.00
    # Orders = 2
    # Units = 7 (2 + 5)
    # AOV = 155.00 / 2 = 77.50
    # COGS = (2 * 15.00) + (5 * 6.00) = 30.00 + 30.00 = 60.00
    # Gross Profit = 155.00 - 60.00 = 95.00
    # Gross Margin = (95.00 / 155.00) * 100 = 61.29%
    # OPEX = 100.00
    # Net Profit = 95.00 - 100.00 = -5.00
    # Net Margin = (-5.00 / 155.00) * 100 = -3.23%

    assert summary.gross_sales.value == Decimal("160.00")
    assert summary.discounts.value == Decimal("5.00")
    assert summary.net_sales.value == Decimal("155.00")
    assert summary.orders.value == Decimal("2")
    assert summary.units_sold.value == Decimal("7")
    assert summary.average_order_value.value == Decimal("77.50")
    assert summary.cogs.value == Decimal("60.00")
    assert summary.gross_profit.value == Decimal("95.00")
    assert summary.gross_margin.value == Decimal("61.29")
    assert summary.operating_expenses.value == Decimal("100.00")
    assert summary.net_profit.value == Decimal("-5.00")
    assert summary.net_margin.value == Decimal("-3.23")
    assert summary.comparison is None


def test_financial_summary_period_over_period(multi_period_db: Session):
    """Verify period-over-period comparison calculations."""
    context = AnalysisContext(
        date_from=datetime(2023, 6, 1, tzinfo=timezone.utc),
        date_to=datetime(2023, 6, 30, 23, 59, 59, tzinfo=timezone.utc),
        comparison_date_from=datetime(2023, 5, 1, tzinfo=timezone.utc),
        comparison_date_to=datetime(2023, 5, 31, 23, 59, 59, tzinfo=timezone.utc),
    )
    summary = FinancialMetricsCalculator.evaluate_summary(multi_period_db, context)

    # June Expected:
    # Net Sales = 140.00 + 200.00 = 340.00
    # COGS = (4 * 15.00) + (10 * 6.00) = 60.00 + 60.00 = 120.00
    # Gross Profit = 340.00 - 120.00 = 220.00
    # Units = 14
    # Orders = 2
    assert summary.net_sales.value == Decimal("340.00")
    assert summary.cogs.value == Decimal("120.00")
    assert summary.gross_profit.value == Decimal("220.00")

    # Comparisons against May:
    # Net Sales May = 155.00, June = 340.00
    # Abs Change = 340 - 155 = +185.00
    # Pct Change = (185 / 155) * 100 = 119.3548%
    assert summary.comparison is not None
    ns_comp = summary.comparison["net_sales"]
    assert ns_comp.current_value == Decimal("340.00")
    assert ns_comp.previous_value == Decimal("155.00")
    assert ns_comp.absolute_change == Decimal("185.00")
    assert ns_comp.percentage_change == 119.3548
    assert ns_comp.direction == TrendDirection.INCREASE


def test_calculate_comparison_zero_denominators():
    """Verify zero denominator and edge case handling in calculate_comparison."""
    # Baseline 0, current 100
    res1 = calculate_comparison(Decimal("100.00"), Decimal("0.00"))
    assert res1.direction == TrendDirection.INCREASE
    assert res1.percentage_change is None
    assert "undefined" in res1.note.lower()

    # Both 0
    res2 = calculate_comparison(Decimal("0.00"), Decimal("0.00"))
    assert res2.direction == TrendDirection.UNCHANGED
    assert res2.percentage_change == 0.0

    # No baseline data
    res3 = calculate_comparison(Decimal("50.00"), None)
    assert res3.direction == TrendDirection.UNDEFINED
    assert res3.previous_value is None

    # Normal decrease
    res4 = calculate_comparison(Decimal("50.00"), Decimal("100.00"))
    assert res4.direction == TrendDirection.DECREASE
    assert res4.absolute_change == Decimal("-50.00")
    assert res4.percentage_change == -50.0


def test_financial_summary_sales_only_no_products(db_session: Session):
    """
    Regression test: When sales exist but 0 products or product costs exist,
    COGS must NOT be fabricated as zero, and Gross Profit/Gross Margin/Net Profit/Net Margin
    must be marked incomplete rather than falsely reporting 100% margin.
    """
    customer = Customer(
        customer_code="CUST-SALES-ONLY",
        name="Sales Only Customer",
        email="salesonly@example.com",
        city="Chicago",
        customer_segment="Retail",
        acquisition_date=date(2023, 1, 1),
    )
    db_session.add(customer)
    db_session.flush()

    sale = Sale(
        transaction_number="TXN-SALES-ONLY-01",
        customer_id=customer.id,
        transaction_date=datetime(2023, 7, 10, 10, 0, tzinfo=timezone.utc),
        status="completed",
        subtotal=Decimal("150.00"),
        discount_amount=Decimal("10.00"),
        tax_amount=Decimal("12.00"),
        total_amount=Decimal("152.00"),
    )
    db_session.add(sale)
    db_session.commit()

    context = AnalysisContext(
        date_from=datetime(2023, 7, 1, tzinfo=timezone.utc),
        date_to=datetime(2023, 7, 31, 23, 59, 59, tzinfo=timezone.utc),
    )

    summary = FinancialMetricsCalculator.evaluate_summary(db_session, context)

    # Sales metrics remain factual and computed
    assert summary.gross_sales.value == Decimal("150.00")
    assert summary.discounts.value == Decimal("10.00")
    assert summary.net_sales.value == Decimal("140.00")
    assert summary.orders.value == Decimal("1")
    assert summary.average_order_value.value == Decimal("140.00")

    # Missing cost metrics must NOT assume zero or fabricate 100% gross margin
    assert summary.cogs.value is None
    assert summary.cogs.formatted == "Incomplete"
    assert summary.gross_profit.value is None
    assert summary.gross_profit.formatted == "Incomplete"
    assert summary.gross_margin.value is None
    assert summary.gross_margin.formatted == "Incomplete"
    assert summary.net_profit.value is None
    assert summary.net_profit.formatted == "Incomplete"
    assert summary.net_margin.value is None
    assert summary.net_margin.formatted == "Incomplete"

    # Verify Evidence Record accurately reflects the missing cost data state
    service = AnalyticsService(db_session)
    summary_res, evidence = service.get_financial_summary(context)

    assert summary_res.cogs.value is None
    assert evidence.data_quality_status == "incomplete"
    assert not any("COGS calculated using catalog product unit_cost." in a for a in evidence.assumptions)
    assert any("Product catalog unit costs are missing; zero COGS is not assumed to prevent fabricated margins." in a for a in evidence.assumptions)
    assert any("marked incomplete because required product unit_cost data is missing" in lim for lim in evidence.limitations)


def test_financial_summary_tenant_isolated_missing_costs(db_session: Session):
    """
    Regression test: Tenant A has products with costs, but Tenant B uploaded sales
    and has 0 products in its catalog. Tenant B must NOT leak Tenant A's products,
    and must report COGS and margins as Incomplete.
    """
    # Tenant A product
    p_a = Product(
        business_id="biz_tenant_a",
        sku="SKU-TENANT-A",
        name="Product A",
        category="Hardware",
        subcategory="Tools",
        unit_cost=Decimal("20.00"),
        selling_price=Decimal("50.00"),
        active=True,
    )
    # Customer for Tenant B
    cust_b = Customer(
        business_id="biz_tenant_b",
        customer_code="CUST-TENANT-B",
        name="Tenant B Buyer",
        email="buyer_b@example.com",
        city="Denver",
        customer_segment="Corporate",
        acquisition_date=date(2023, 3, 1),
    )
    db_session.add_all([p_a, cust_b])
    db_session.flush()

    # Tenant B sale (Tenant B has NO products in catalog)
    sale_b = Sale(
        business_id="biz_tenant_b",
        transaction_number="TXN-BIZ-B-01",
        customer_id=cust_b.id,
        transaction_date=datetime(2023, 8, 10, 10, 0, tzinfo=timezone.utc),
        status="completed",
        subtotal=Decimal("200.00"),
        discount_amount=Decimal("0.00"),
        tax_amount=Decimal("16.00"),
        total_amount=Decimal("216.00"),
    )
    db_session.add(sale_b)
    db_session.flush()

    item_b = SaleItem(
        sale_id=sale_b.id,
        product_id=p_a.id,
        quantity=4,
        unit_price=Decimal("50.00"),
        discount_amount=Decimal("0.00"),
        line_total=Decimal("200.00"),
    )
    db_session.add(item_b)
    db_session.commit()

    context_b = AnalysisContext(
        business_id="biz_tenant_b",
        date_from=datetime(2023, 8, 1, tzinfo=timezone.utc),
        date_to=datetime(2023, 8, 31, 23, 59, 59, tzinfo=timezone.utc),
    )

    summary_b = FinancialMetricsCalculator.evaluate_summary(db_session, context_b)

    assert summary_b.net_sales.value == Decimal("200.00")
    assert summary_b.cogs.value is None
    assert summary_b.cogs.formatted == "Incomplete"
    assert summary_b.gross_profit.value is None
    assert summary_b.gross_profit.formatted == "Incomplete"
    assert summary_b.gross_margin.value is None
    assert summary_b.gross_margin.formatted == "Incomplete"


def test_financial_summary_sales_only_period_over_period(db_session: Session):
    """
    Regression test: Period-over-period comparisons with missing COGS/profit
    do not crash and handle None metric values safely.
    """
    customer = Customer(
        customer_code="CUST-POP",
        name="POP Customer",
        email="pop@example.com",
        city="Austin",
        customer_segment="Retail",
        acquisition_date=date(2023, 1, 1),
    )
    db_session.add(customer)
    db_session.flush()

    s_may = Sale(
        transaction_number="TXN-POP-MAY",
        customer_id=customer.id,
        transaction_date=datetime(2023, 5, 15, 10, 0, tzinfo=timezone.utc),
        status="completed",
        subtotal=Decimal("100.00"),
        discount_amount=Decimal("0.00"),
        tax_amount=Decimal("8.00"),
        total_amount=Decimal("108.00"),
    )
    s_june = Sale(
        transaction_number="TXN-POP-JUNE",
        customer_id=customer.id,
        transaction_date=datetime(2023, 6, 15, 10, 0, tzinfo=timezone.utc),
        status="completed",
        subtotal=Decimal("200.00"),
        discount_amount=Decimal("0.00"),
        tax_amount=Decimal("16.00"),
        total_amount=Decimal("216.00"),
    )
    db_session.add_all([s_may, s_june])
    db_session.commit()

    context = AnalysisContext(
        date_from=datetime(2023, 6, 1, tzinfo=timezone.utc),
        date_to=datetime(2023, 6, 30, 23, 59, 59, tzinfo=timezone.utc),
        comparison_date_from=datetime(2023, 5, 1, tzinfo=timezone.utc),
        comparison_date_to=datetime(2023, 5, 31, 23, 59, 59, tzinfo=timezone.utc),
    )

    summary = FinancialMetricsCalculator.evaluate_summary(db_session, context)

    assert summary.net_sales.value == Decimal("200.00")
    assert summary.comparison is not None
    # Net sales comparison works normally
    assert summary.comparison["net_sales"].direction == TrendDirection.INCREASE
    assert summary.comparison["net_sales"].percentage_change == 100.0

    # COGS and Gross Profit comparisons handle None values gracefully
    cogs_comp = summary.comparison["cogs"]
    assert cogs_comp.current_value is None
    assert cogs_comp.previous_value is None
    assert cogs_comp.direction == TrendDirection.UNDEFINED

    gp_comp = summary.comparison["gross_profit"]
    assert gp_comp.current_value is None
    assert gp_comp.previous_value is None
    assert gp_comp.direction == TrendDirection.UNDEFINED


def test_financial_summary_sales_only_inr_currency(db_session: Session):
    """
    Regression test: Sales-only tenant with INR currency must:
    1. Resolve active currency symbol as '₹'.
    2. Format Net Sales with '₹' (e.g., '₹140.00').
    3. Keep COGS, Gross Profit, Gross Margin, and Net Profit as None / 'Incomplete'.
    4. Never convert missing COGS to ₹0.00 or 0.00%.
    """
    from app.models.tenant import Business, Organization

    org = Organization(id="org_inr_test", name="INR Test Org", slug="inr-test-org")
    biz = Business(
        id="biz_inr_sales_only",
        organization_id=org.id,
        name="INR Sales Only Biz",
        currency="INR",
        status="active",
    )
    cust = Customer(
        business_id=biz.id,
        customer_code="CUST-INR-01",
        name="INR Customer",
        email="inr@example.com",
        city="Mumbai",
        customer_segment="Retail",
        acquisition_date=date(2024, 1, 1),
    )
    db_session.add_all([org, biz, cust])
    db_session.flush()

    sale = Sale(
        business_id=biz.id,
        transaction_number="TXN-INR-001",
        customer_id=cust.id,
        transaction_date=datetime(2024, 6, 15, 12, 0, tzinfo=timezone.utc),
        status="completed",
        subtotal=Decimal("150.00"),
        discount_amount=Decimal("10.00"),
        tax_amount=Decimal("25.20"),
        total_amount=Decimal("165.20"),
    )
    db_session.add(sale)
    db_session.commit()

    service = AnalyticsService(db_session, business_id=biz.id)
    context = AnalysisContext(
        business_id=biz.id,
        date_from=datetime(2024, 6, 1, tzinfo=timezone.utc),
        date_to=datetime(2024, 6, 30, 23, 59, 59, tzinfo=timezone.utc),
    )

    summary, evidence = service.get_financial_summary(context)

    # Currency verification
    assert summary.currency == "INR"
    assert summary.currency_symbol == "₹"

    # Net Sales is subtotal (150) - discount (10) = 140
    assert summary.net_sales.value == Decimal("140.00")
    assert summary.net_sales.formatted == "₹140.00"

    # Missing cost data MUST remain None and 'Incomplete', never ₹0.00 or 0.00%
    assert summary.cogs.value is None
    assert summary.cogs.formatted == "Incomplete"
    assert summary.gross_profit.value is None
    assert summary.gross_profit.formatted == "Incomplete"
    assert summary.gross_margin.value is None
    assert summary.gross_margin.formatted == "Incomplete"
    assert summary.net_profit.value is None
    assert summary.net_profit.formatted == "Incomplete"
    assert summary.net_margin.value is None
    assert summary.net_margin.formatted == "Incomplete"

    # Evidence audit trail reflects incomplete status and INR symbol
    assert evidence.data_quality_status == "incomplete"
    assert any("Product catalog unit costs are missing; zero COGS is not assumed" in a for a in evidence.assumptions)


