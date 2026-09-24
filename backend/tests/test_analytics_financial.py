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


@pytest.fixture
def multi_period_db(db_session: Session) -> Session:
    """Populate database with multi-period retail data for financial verification."""
    now = datetime(2023, 6, 30, tzinfo=timezone.utc)

    # Customers
    c1 = Customer(
        customer_code="CUST-001",
        name="Corp Buyer A",
        email="buyer@corpa.com",
        city="Seattle",
        customer_segment="Corporate",
        acquisition_date=date(2023, 1, 10),
    )
    c2 = Customer(
        customer_code="CUST-002",
        name="Retail Buyer B",
        email="buyer@retailb.com",
        city="Portland",
        customer_segment="Retail",
        acquisition_date=date(2023, 2, 15),
    )
    db_session.add_all([c1, c2])
    db_session.flush()

    # Products
    p1 = Product(
        sku="SKU-A",
        name="Widget A",
        category="Hardware",
        subcategory="Tools",
        unit_cost=Decimal("15.00"),
        selling_price=Decimal("35.00"),
        active=True,
    )
    p2 = Product(
        sku="SKU-B",
        name="Gadget B",
        category="Electronics",
        subcategory="Accessories",
        unit_cost=Decimal("6.00"),
        selling_price=Decimal("18.00"),
        active=True,
    )
    db_session.add_all([p1, p2])
    db_session.flush()

    # Inventory
    inv1 = Inventory(
        product_id=p1.id,
        stock_quantity=50,
        reorder_threshold=10,
        warehouse_location="Warehouse North",
    )
    inv2 = Inventory(
        product_id=p2.id,
        stock_quantity=3,
        reorder_threshold=10,
        warehouse_location="Warehouse South",
    )
    db_session.add_all([inv1, inv2])
    db_session.flush()

    # May 2023 (Baseline period)
    # Sale 1: 2 x SKU-A @ 35.00, discount 5.00 => line_total = 65.00, subtotal = 70.00
    s1 = Sale(
        transaction_number="TXN-202305-01",
        customer_id=c1.id,
        transaction_date=datetime(2023, 5, 10, 10, 0, tzinfo=timezone.utc),
        status="completed",
        subtotal=Decimal("70.00"),
        discount_amount=Decimal("5.00"),
        tax_amount=Decimal("5.20"),
        total_amount=Decimal("70.20"),
    )
    db_session.add(s1)
    db_session.flush()
    i1 = SaleItem(
        sale_id=s1.id,
        product_id=p1.id,
        quantity=2,
        unit_price=Decimal("35.00"),
        discount_amount=Decimal("5.00"),
        line_total=Decimal("65.00"),
    )
    db_session.add(i1)

    # Sale 2: 5 x SKU-B @ 18.00, discount 0.00 => line_total = 90.00, subtotal = 90.00
    s2 = Sale(
        transaction_number="TXN-202305-02",
        customer_id=c2.id,
        transaction_date=datetime(2023, 5, 20, 14, 0, tzinfo=timezone.utc),
        status="completed",
        subtotal=Decimal("90.00"),
        discount_amount=Decimal("0.00"),
        tax_amount=Decimal("7.20"),
        total_amount=Decimal("97.20"),
    )
    db_session.add(s2)
    db_session.flush()
    i2 = SaleItem(
        sale_id=s2.id,
        product_id=p2.id,
        quantity=5,
        unit_price=Decimal("18.00"),
        discount_amount=Decimal("0.00"),
        line_total=Decimal("90.00"),
    )
    db_session.add(i2)

    # June 2023 (Current period)
    # Sale 3: 4 x SKU-A @ 35.00, discount 0.00 => line_total = 140.00
    s3 = Sale(
        transaction_number="TXN-202306-01",
        customer_id=c1.id,
        transaction_date=datetime(2023, 6, 5, 11, 0, tzinfo=timezone.utc),
        status="completed",
        subtotal=Decimal("140.00"),
        discount_amount=Decimal("0.00"),
        tax_amount=Decimal("11.20"),
        total_amount=Decimal("151.20"),
    )
    db_session.add(s3)
    db_session.flush()
    i3 = SaleItem(
        sale_id=s3.id,
        product_id=p1.id,
        quantity=4,
        unit_price=Decimal("35.00"),
        discount_amount=Decimal("0.00"),
        line_total=Decimal("140.00"),
    )
    db_session.add(i3)

    # Sale 4: 10 x SKU-B @ 20.00, discount 0.00 => line_total = 200.00
    s4 = Sale(
        transaction_number="TXN-202306-02",
        customer_id=c1.id,
        transaction_date=datetime(2023, 6, 20, 16, 0, tzinfo=timezone.utc),
        status="completed",
        subtotal=Decimal("200.00"),
        discount_amount=Decimal("0.00"),
        tax_amount=Decimal("16.00"),
        total_amount=Decimal("216.00"),
    )
    db_session.add(s4)
    db_session.flush()
    i4 = SaleItem(
        sale_id=s4.id,
        product_id=p2.id,
        quantity=10,
        unit_price=Decimal("20.00"),
        discount_amount=Decimal("0.00"),
        line_total=Decimal("200.00"),
    )
    db_session.add(i4)

    # Operating Expenses
    # May: 100.00 rent
    exp_may = Expense(
        expense_date=date(2023, 5, 1),
        category="Rent",
        description="May Rent",
        amount=Decimal("100.00"),
        recurring=True,
    )
    # June: 120.00 rent
    exp_june = Expense(
        expense_date=date(2023, 6, 1),
        category="Rent",
        description="June Rent",
        amount=Decimal("120.00"),
        recurring=True,
    )
    db_session.add_all([exp_may, exp_june])
    db_session.commit()
    return db_session


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
