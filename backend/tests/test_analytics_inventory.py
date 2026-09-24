"""Tests for inventory valuation, stock level classifications, and turnover ratio."""

from datetime import datetime, timezone
from decimal import Decimal
import pytest
from sqlalchemy.orm import Session
from app.analytics.core.context import AnalysisContext
from app.analytics.inventory.stock import InventoryStockAnalyzer
from app.analytics.inventory.turnover import InventoryTurnoverCalculator
from app.models.inventory import Inventory
from app.models.product import Product


def test_inventory_overview(multi_period_db: Session):
    """Verify stock quantities, valuation, and low stock threshold alerts."""
    # Inventory is already populated in multi_period_db fixture
    # Product 1 (SKU-A): unit_cost = 15.00, stock = 50, threshold = 10 -> valuation = 750.00 (in_stock)
    # Product 2 (SKU-B): unit_cost = 6.00, stock = 3, threshold = 10 -> valuation = 18.00 (low_stock)

    overview = InventoryStockAnalyzer.evaluate(multi_period_db)

    assert overview.total_skus == 2
    assert overview.total_physical_units == 53
    assert overview.total_inventory_valuation == Decimal("768.00")
    assert overview.low_stock_count == 1
    assert overview.adequate_stock_count == 1
    assert len(overview.low_stock_items) == 1
    assert overview.low_stock_items[0].sku == "SKU-B"


def test_inventory_turnover(multi_period_db: Session):
    """Verify inventory turnover ratio and DSI calculation."""
    context = AnalysisContext(
        date_from=datetime(2023, 5, 1, tzinfo=timezone.utc),
        date_to=datetime(2023, 6, 30, tzinfo=timezone.utc),
    )
    res = InventoryTurnoverCalculator.evaluate(multi_period_db, context)

    assert res.period_cogs > Decimal("0.00")
    assert res.inventory_valuation > Decimal("0.00")
    assert res.turnover_ratio is not None
    assert res.days_sales_of_inventory is not None
    assert len(res.assumptions_and_limitations) >= 2
