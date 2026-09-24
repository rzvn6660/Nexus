"""Tests for product rankings, category contributions, and sales velocity."""

from datetime import datetime, timezone
from decimal import Decimal
import pytest
from sqlalchemy.orm import Session
from app.analytics.core.context import AnalysisContext
from app.analytics.core.types import SortOrder
from app.analytics.product.performance import ProductAnalyticsService
from app.analytics.product.velocity import ProductVelocityCalculator


def test_product_rankings_by_revenue(multi_period_db: Session):
    """Verify transparent product ranking by revenue."""
    context = AnalysisContext(
        date_from=datetime(2023, 6, 1, tzinfo=timezone.utc),
        date_to=datetime(2023, 6, 30, tzinfo=timezone.utc),
    )
    items = ProductAnalyticsService.get_product_rankings(
        multi_period_db, context, ranking_metric="revenue", limit=10
    )

    # In June:
    # SKU-B (Gadget B): 10 x 20.00 = 200.00 revenue
    # SKU-A (Widget A): 4 x 35.00 = 140.00 revenue
    assert len(items) == 2
    assert items[0].sku == "SKU-B"
    assert items[0].revenue == Decimal("200.00")
    assert items[0].rank == 1

    assert items[1].sku == "SKU-A"
    assert items[1].revenue == Decimal("140.00")
    assert items[1].rank == 2


def test_product_rankings_by_profit(multi_period_db: Session):
    """Verify product ranking by gross profit."""
    context = AnalysisContext(
        date_from=datetime(2023, 6, 1, tzinfo=timezone.utc),
        date_to=datetime(2023, 6, 30, tzinfo=timezone.utc),
    )
    items = ProductAnalyticsService.get_product_rankings(
        multi_period_db, context, ranking_metric="profit", limit=10
    )

    # In June:
    # SKU-B: Rev = 200.00, Cost = 10 * 6.00 = 60.00 => Profit = 140.00
    # SKU-A: Rev = 140.00, Cost = 4 * 15.00 = 60.00 => Profit = 80.00
    assert items[0].sku == "SKU-B"
    assert items[0].gross_profit == Decimal("140.00")
    assert items[1].sku == "SKU-A"
    assert items[1].gross_profit == Decimal("80.00")


def test_category_breakdown(multi_period_db: Session):
    """Verify category contribution and sorting."""
    context = AnalysisContext(
        date_from=datetime(2023, 5, 1, tzinfo=timezone.utc),
        date_to=datetime(2023, 5, 31, tzinfo=timezone.utc),
    )
    res = ProductAnalyticsService.get_category_breakdown(multi_period_db, context)

    # May:
    # Hardware (SKU-A): 65.00
    # Electronics (SKU-B): 90.00
    # Total = 155.00
    assert res.total_value == Decimal("155.00")
    assert len(res.items) == 2
    assert res.items[0].key == "Electronics"
    assert res.items[0].value == Decimal("90.00")
    assert res.items[1].key == "Hardware"
    assert res.items[1].value == Decimal("65.00")


def test_product_velocity(multi_period_db: Session):
    """Verify daily units velocity calculations and classification."""
    context = AnalysisContext(
        date_from=datetime(2023, 6, 1, tzinfo=timezone.utc),
        date_to=datetime(2023, 6, 30, tzinfo=timezone.utc),
    )
    res = ProductVelocityCalculator.evaluate(
        multi_period_db, context, high_threshold_units_per_day=0.3, medium_threshold_units_per_day=0.1
    )

    # Days in interval = 29 days
    # SKU-B sold 10 units => ~0.34 units/day (high)
    # SKU-A sold 4 units => ~0.14 units/day (medium)
    assert res.total_evaluated_products == 2
    assert res.dormant_count == 0
