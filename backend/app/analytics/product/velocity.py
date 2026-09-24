"""Inventory and product sales velocity analytics."""

from decimal import Decimal
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field
from sqlalchemy import select, func, and_
from sqlalchemy.orm import Session
from app.models.product import Product
from app.models.sale import Sale
from app.models.sale_item import SaleItem
from app.analytics.core.context import AnalysisContext


class ProductVelocityItem(BaseModel):
    """Detailed velocity analysis for a single SKU."""
    product_id: int
    sku: str
    name: str
    category: str
    units_sold: int
    days_in_period: float
    units_per_day: float
    velocity_classification: str  # high, medium, slow_moving, dormant


class VelocityAnalysisResult(BaseModel):
    """Summary of product sales velocity across catalog."""
    total_evaluated_products: int
    high_velocity_count: int
    medium_velocity_count: int
    slow_moving_count: int
    dormant_count: int
    products: List[ProductVelocityItem]


class ProductVelocityCalculator:
    """Computes daily sales velocity and identifies fast and slow-moving SKUs."""

    @classmethod
    def evaluate(
        cls,
        session: Session,
        context: AnalysisContext,
        high_threshold_units_per_day: float = 5.0,
        medium_threshold_units_per_day: float = 1.0,
    ) -> VelocityAnalysisResult:
        """
        Evaluate physical units sold per day for each active product.
        
        Velocity = Units Sold / Days in Period.
        Classification:
          - Dormant: 0 units sold in period
          - Slow-moving: > 0 and < medium_threshold
          - Medium: >= medium_threshold and < high_threshold
          - High: >= high_threshold
        """
        days = 30.0
        if context.date_from and context.date_to:
            diff = (context.date_to - context.date_from).total_seconds() / 86400.0
            days = max(diff, 1.0)

        # Left join Product to SaleItem to capture products with zero sales in period
        stmt = (
            select(
                Product.id.label("product_id"),
                Product.sku.label("sku"),
                Product.name.label("name"),
                Product.category.label("category"),
                func.coalesce(func.sum(SaleItem.quantity), 0).label("units_sold"),
            )
            .outerjoin(
                SaleItem,
                and_(
                    Product.id == SaleItem.product_id,
                    SaleItem.sale_id.in_(
                        select(Sale.id).where(
                            and_(
                                Sale.transaction_date >= context.date_from
                                if context.date_from
                                else True,
                                Sale.transaction_date <= context.date_to
                                if context.date_to
                                else True,
                                Sale.status.in_(context.statuses) if context.statuses else True,
                            )
                        )
                    ),
                ),
            )
            .where(Product.active.is_(True))
            .group_by(Product.id)
            .order_by(func.coalesce(func.sum(SaleItem.quantity), 0).desc())
        )

        rows = session.execute(stmt).all()

        products: List[ProductVelocityItem] = []
        high_c = 0
        med_c = 0
        slow_c = 0
        dorm_c = 0

        for r in rows:
            units = int(r.units_sold)
            upd = round(float(units) / days, 3)

            if units == 0:
                classification = "dormant"
                dorm_c += 1
            elif upd < medium_threshold_units_per_day:
                classification = "slow_moving"
                slow_c += 1
            elif upd < high_threshold_units_per_day:
                classification = "medium"
                med_c += 1
            else:
                classification = "high"
                high_c += 1

            products.append(
                ProductVelocityItem(
                    product_id=r.product_id,
                    sku=r.sku,
                    name=r.name,
                    category=r.category,
                    units_sold=units,
                    days_in_period=round(days, 1),
                    units_per_day=upd,
                    velocity_classification=classification,
                )
            )

        return VelocityAnalysisResult(
            total_evaluated_products=len(products),
            high_velocity_count=high_c,
            medium_velocity_count=med_c,
            slow_moving_count=slow_c,
            dormant_count=dorm_c,
            products=products,
        )
