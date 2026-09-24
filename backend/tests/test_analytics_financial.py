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
