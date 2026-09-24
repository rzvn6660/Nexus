"""Deterministic inventory turnover ratio and Days Sales of Inventory (DSI) analytics."""

from decimal import Decimal, ROUND_HALF_UP
from typing import Optional, List
from pydantic import BaseModel, Field
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from app.models.product import Product
from app.models.inventory import Inventory
from app.analytics.core.context import AnalysisContext
from app.analytics.metrics.financial import FinancialMetricsCalculator


class InventoryTurnoverResult(BaseModel):
    """Inventory turnover and Days Sales of Inventory (DSI) analysis."""
    period_cogs: Decimal
    inventory_valuation: Decimal
    turnover_ratio: Optional[float] = Field(
        default=None,
        description="Turnover = COGS / Inventory Valuation. Undefined if valuation is zero."
    )
    days_in_period: float
    days_sales_of_inventory: Optional[float] = Field(
        default=None,
        description="DSI = (Inventory Valuation / COGS) * Days. Undefined if COGS is zero."
    )
    interpretation: str
    assumptions_and_limitations: List[str]


class InventoryTurnoverCalculator:
    """Computes inventory turnover ratio with explicit assumptions."""

    @classmethod
    def evaluate(
        cls, session: Session, context: AnalysisContext
    ) -> InventoryTurnoverResult:
        """
        Compute Inventory Turnover Ratio = COGS / Inventory Value.
        
        Assumptions:
        - Uses current inventory snapshot as proxy for average inventory over the period.
        - Requires a non-zero time interval.
        """
        days = 365.0
        if context.date_from and context.date_to:
            diff = (context.date_to - context.date_from).total_seconds() / 86400.0
            days = max(diff, 1.0)

        # 1. COGS for the evaluation period
        u_agg = FinancialMetricsCalculator.compute_units_and_cogs(session, context)
        cogs = u_agg["cogs"]

        # 2. Total inventory valuation
        inv_stmt = select(
            func.coalesce(
                func.sum(Inventory.stock_quantity * Product.unit_cost), Decimal("0.00")
            )
        ).join(Product, Inventory.product_id == Product.id)
        if context.categories:
            inv_stmt = inv_stmt.where(Product.category.in_(context.categories))
        inv_val = Decimal(str(session.execute(inv_stmt).scalar_one())).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )

        turnover: Optional[float] = None
        dsi: Optional[float] = None

        if inv_val > 0:
            turnover = round(float(cogs / inv_val), 3)

        if cogs > 0:
            dsi = round(float((inv_val / cogs) * Decimal(str(days))), 1)

        interp = (
            f"The business turned over its inventory approximately {turnover:.2f} times during the "
            f"{int(days)}-day period, taking an estimated {dsi:.1f} days to sell current inventory on hand."
            if (turnover is not None and dsi is not None)
            else "Turnover ratio or DSI could not be computed due to zero COGS or zero inventory valuation."
        )

        return InventoryTurnoverResult(
            period_cogs=cogs,
            inventory_valuation=inv_val,
            turnover_ratio=turnover,
            days_in_period=days,
            days_sales_of_inventory=dsi,
            interpretation=interp,
            assumptions_and_limitations=[
                "Uses point-in-time inventory stock levels as a proxy for average inventory over the period.",
                "Actual periodic opening and closing inventory history is not recorded in the Phase 2 schema.",
                "COGS calculations assume static catalog product unit_cost.",
            ],
        )
