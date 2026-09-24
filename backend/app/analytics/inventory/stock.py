"""Deterministic inventory stock valuation and replenishment threshold analytics."""

from decimal import Decimal, ROUND_HALF_UP
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field
from sqlalchemy import select, func, and_
from sqlalchemy.orm import Session
from app.models.product import Product
from app.models.inventory import Inventory
from app.analytics.core.models import BreakdownItem, BreakdownResult


class StockStatusItem(BaseModel):
    """Inventory status detail for a product."""
    product_id: int
    sku: str
    name: str
    category: str
    warehouse_location: str
    stock_quantity: int
    reorder_threshold: int
    unit_cost: Decimal
    stock_value: Decimal
    status: str  # in_stock, low_stock, out_of_stock


class InventoryOverviewResult(BaseModel):
    """Aggregate stock health scorecard."""
    total_skus: int
    total_physical_units: int
    total_inventory_valuation: Decimal
    out_of_stock_count: int
    low_stock_count: int
    adequate_stock_count: int
    warehouse_breakdown: BreakdownResult
    low_stock_items: List[StockStatusItem]


class InventoryStockAnalyzer:
    """Calculates physical stock metrics, monetary valuations, and replenishment alerts."""

    @classmethod
    def evaluate(
        cls,
        session: Session,
        warehouse: Optional[str] = None,
        category: Optional[str] = None,
    ) -> InventoryOverviewResult:
        """
        Evaluate current inventory snapshot across all active products.
        """
        stmt = (
            select(
                Product.id.label("product_id"),
                Product.sku.label("sku"),
                Product.name.label("name"),
                Product.category.label("category"),
                Product.unit_cost.label("unit_cost"),
                Inventory.stock_quantity.label("stock_quantity"),
                Inventory.reorder_threshold.label("reorder_threshold"),
                Inventory.warehouse_location.label("warehouse_location"),
            )
            .join(Inventory, Product.id == Inventory.product_id)
            .where(Product.active.is_(True))
        )

        if warehouse:
            stmt = stmt.where(Inventory.warehouse_location == warehouse)
        if category:
            stmt = stmt.where(Product.category == category)

        rows = session.execute(stmt).all()

        total_skus = len(rows)
        total_units = 0
        total_val = Decimal("0.00")
        oos_c = 0
        low_c = 0
        adeq_c = 0
        warehouse_map: Dict[str, Dict[str, Any]] = {}
        low_stock_list: List[StockStatusItem] = []

        for r in rows:
            qty = int(r.stock_quantity)
            thresh = int(r.reorder_threshold)
            cost = Decimal(str(r.unit_cost)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            item_val = (cost * qty).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

            total_units += qty
            total_val += item_val

            if qty == 0:
                status = "out_of_stock"
                oos_c += 1
            elif qty <= thresh:
                status = "low_stock"
                low_c += 1
            else:
                status = "in_stock"
                adeq_c += 1

            item = StockStatusItem(
                product_id=r.product_id,
                sku=r.sku,
                name=r.name,
                category=r.category,
                warehouse_location=r.warehouse_location,
                stock_quantity=qty,
                reorder_threshold=thresh,
                unit_cost=cost,
                stock_value=item_val,
                status=status,
            )

            if status in ("out_of_stock", "low_stock"):
                low_stock_list.append(item)

            wh = r.warehouse_location
            if wh not in warehouse_map:
                warehouse_map[wh] = {"units": 0, "val": Decimal("0.00"), "count": 0}
            warehouse_map[wh]["units"] += qty
            warehouse_map[wh]["val"] += item_val
            warehouse_map[wh]["count"] += 1

        # Sort low stock list by severity: 0 qty first, then lowest qty
        low_stock_list.sort(key=lambda x: (x.stock_quantity, x.reorder_threshold))

        # Warehouse breakdown
        wh_items: List[BreakdownItem] = []
        for wh, data in warehouse_map.items():
            wh_val = data["val"]
            pct = (
                round(float((wh_val / total_val) * Decimal("100.0")), 2)
                if total_val > 0
                else 0.0
            )
            wh_items.append(
                BreakdownItem(
                    key=wh,
                    label=wh,
                    value=wh_val,
                    formatted_value=f"${wh_val:,.2f}",
                    percentage_of_total=pct,
                    count=data["count"],
                    metadata={"units": data["units"]},
                )
            )

        wh_items.sort(key=lambda x: x.value, reverse=True)
        wh_breakdown = BreakdownResult(
            dimension="warehouse_location",
            metric="valuation",
            total_value=total_val,
            items=wh_items,
        )

        return InventoryOverviewResult(
            total_skus=total_skus,
            total_physical_units=total_units,
            total_inventory_valuation=total_val,
            out_of_stock_count=oos_c,
            low_stock_count=low_c,
            adequate_stock_count=adeq_c,
            warehouse_breakdown=wh_breakdown,
            low_stock_items=low_stock_list,
        )
