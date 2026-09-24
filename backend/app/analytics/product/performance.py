"""Deterministic product and category analytical computations."""

from decimal import Decimal, ROUND_HALF_UP
from typing import List, Dict, Any, Optional
from sqlalchemy import select, func, and_, desc, asc
from sqlalchemy.orm import Session
from app.models.product import Product
from app.models.sale import Sale
from app.models.sale_item import SaleItem
from app.analytics.core.context import AnalysisContext
from app.analytics.core.types import SortOrder
from app.analytics.core.models import (
    ProductPerformanceItem,
    BreakdownResult,
    BreakdownItem,
)


class ProductAnalyticsService:
    """Calculates product and category rankings, margins, and contributions."""

    @classmethod
    def get_product_rankings(
        cls,
        session: Session,
        context: AnalysisContext,
        ranking_metric: str = "revenue",
        limit: int = 50,
        sort_order: SortOrder = SortOrder.DESC,
    ) -> List[ProductPerformanceItem]:
        """
        Rank products based on an explicit, transparent metric:
        'revenue', 'gross_profit', 'units_sold', 'order_count', or 'gross_margin'.
        
        Never computes an opaque 'best product' score.
        """
        # Duration in days for velocity
        days = 1.0
        if context.date_from and context.date_to:
            diff = (context.date_to - context.date_from).total_seconds() / 86400.0
            days = max(diff, 1.0)

        # 1. Total revenue for contribution denominator
        total_rev_stmt = select(func.coalesce(func.sum(SaleItem.line_total), Decimal("0.00"))).join(
            Sale, SaleItem.sale_id == Sale.id
        )
        if context.date_from:
            total_rev_stmt = total_rev_stmt.where(Sale.transaction_date >= context.date_from)
        if context.date_to:
            total_rev_stmt = total_rev_stmt.where(Sale.transaction_date <= context.date_to)
        if context.statuses:
            total_rev_stmt = total_rev_stmt.where(Sale.status.in_(context.statuses))
        total_market_revenue = Decimal(str(session.execute(total_rev_stmt).scalar_one()))

        # 2. Product-level aggregation
        stmt = (
            select(
                Product.id.label("product_id"),
                Product.sku.label("sku"),
                Product.name.label("name"),
                Product.category.label("category"),
                Product.subcategory.label("subcategory"),
                func.coalesce(func.sum(SaleItem.quantity), 0).label("units_sold"),
                func.count(func.distinct(SaleItem.sale_id)).label("order_count"),
                func.coalesce(func.sum(SaleItem.line_total), Decimal("0.00")).label("revenue"),
                func.coalesce(
                    func.sum(SaleItem.quantity * Product.unit_cost), Decimal("0.00")
                ).label("cogs"),
            )
            .join(SaleItem, Product.id == SaleItem.product_id)
            .join(Sale, SaleItem.sale_id == Sale.id)
            .group_by(Product.id)
        )

        clauses = []
        if context.date_from:
            clauses.append(Sale.transaction_date >= context.date_from)
        if context.date_to:
            clauses.append(Sale.transaction_date <= context.date_to)
        if context.statuses:
            clauses.append(Sale.status.in_(context.statuses))
        if context.categories:
            clauses.append(Product.category.in_(context.categories))
        if context.subcategories:
            clauses.append(Product.subcategory.in_(context.subcategories))
        if context.product_ids:
            clauses.append(Product.id.in_(context.product_ids))
        if clauses:
            stmt = stmt.where(and_(*clauses))

        rows = session.execute(stmt).all()

        items: List[ProductPerformanceItem] = []
        for r in rows:
            revenue = Decimal(str(r.revenue)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            cogs = Decimal(str(r.cogs)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            profit = (revenue - cogs).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            margin_pct = (
                round(float((profit / revenue) * Decimal("100.0")), 2) if revenue > 0 else 0.0
            )
            contrib_pct = (
                round(float((revenue / total_market_revenue) * Decimal("100.0")), 2)
                if total_market_revenue > 0
                else 0.0
            )
            velocity = round(float(r.units_sold) / days, 2)

            items.append(
                ProductPerformanceItem(
                    product_id=r.product_id,
                    sku=r.sku,
                    name=r.name,
                    category=r.category,
                    subcategory=r.subcategory,
                    units_sold=int(r.units_sold),
                    order_count=int(r.order_count),
                    revenue=revenue,
                    cogs=cogs,
                    gross_profit=profit,
                    gross_margin_pct=margin_pct,
                    revenue_contribution_pct=contrib_pct,
                    velocity_units_per_day=velocity,
                    rank=0,  # Assigned after sorting
                )
            )

        # Sort transparently by requested metric
        reverse_flag = sort_order == SortOrder.DESC
        metric_key = ranking_metric.lower()
        if metric_key == "gross_profit" or metric_key == "profit":
            items.sort(key=lambda x: x.gross_profit, reverse=reverse_flag)
        elif metric_key == "units_sold" or metric_key == "units":
            items.sort(key=lambda x: x.units_sold, reverse=reverse_flag)
        elif metric_key == "order_count" or metric_key == "orders":
            items.sort(key=lambda x: x.order_count, reverse=reverse_flag)
        elif metric_key == "gross_margin" or metric_key == "margin":
            items.sort(key=lambda x: x.gross_margin_pct or 0.0, reverse=reverse_flag)
        elif metric_key == "velocity":
            items.sort(key=lambda x: x.velocity_units_per_day or 0.0, reverse=reverse_flag)
        else:  # default revenue
            items.sort(key=lambda x: x.revenue, reverse=reverse_flag)

        # Assign ranks
        for idx, item in enumerate(items[:limit], 1):
            item.rank = idx

        return items[:limit]

    @classmethod
    def get_category_breakdown(
        cls,
        session: Session,
        context: AnalysisContext,
        metric: str = "revenue",
    ) -> BreakdownResult:
        """
        Evaluate category performance and contribution.
        Supports sorting by 'revenue', 'profit', 'units', or 'orders'.
        """
        stmt = (
            select(
                Product.category.label("category"),
                func.coalesce(func.sum(SaleItem.line_total), Decimal("0.00")).label("revenue"),
                func.coalesce(
                    func.sum(SaleItem.quantity * Product.unit_cost), Decimal("0.00")
                ).label("cogs"),
                func.coalesce(func.sum(SaleItem.quantity), 0).label("units"),
                func.count(func.distinct(SaleItem.sale_id)).label("orders"),
            )
            .join(SaleItem, Product.id == SaleItem.product_id)
            .join(Sale, SaleItem.sale_id == Sale.id)
            .group_by(Product.category)
        )

        clauses = []
        if context.date_from:
            clauses.append(Sale.transaction_date >= context.date_from)
        if context.date_to:
            clauses.append(Sale.transaction_date <= context.date_to)
        if context.statuses:
            clauses.append(Sale.status.in_(context.statuses))
        if clauses:
            stmt = stmt.where(and_(*clauses))

        rows = session.execute(stmt).all()

        total_rev = Decimal("0.00")
        raw_items = []
        for r in rows:
            rev = Decimal(str(r.revenue)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            cogs = Decimal(str(r.cogs)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            profit = (rev - cogs).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            units = int(r.units)
            orders = int(r.orders)
            margin_pct = round(float((profit / rev) * Decimal("100.0")), 2) if rev > 0 else 0.0

            total_rev += rev
            raw_items.append(
                {
                    "category": r.category,
                    "revenue": rev,
                    "profit": profit,
                    "cogs": cogs,
                    "units": units,
                    "orders": orders,
                    "margin_pct": margin_pct,
                }
            )

        # Sort items based on requested metric
        m_lower = metric.lower()
        if m_lower in ("profit", "gross_profit"):
            raw_items.sort(key=lambda x: x["profit"], reverse=True)
            active_metric_key = "profit"
        elif m_lower in ("units", "units_sold"):
            raw_items.sort(key=lambda x: x["units"], reverse=True)
            active_metric_key = "units"
        elif m_lower in ("orders", "order_count"):
            raw_items.sort(key=lambda x: x["orders"], reverse=True)
            active_metric_key = "orders"
        else:
            raw_items.sort(key=lambda x: x["revenue"], reverse=True)
            active_metric_key = "revenue"

        items: List[BreakdownItem] = []
        for item in raw_items:
            val = item[active_metric_key]
            if isinstance(val, int):
                val_dec = Decimal(val)
                fmt = f"{val:,}"
            else:
                val_dec = val
                fmt = f"${val:,.2f}"

            share = (
                round(float((item["revenue"] / total_rev) * Decimal("100.0")), 2)
                if total_rev > 0
                else 0.0
            )

            items.append(
                BreakdownItem(
                    key=item["category"],
                    label=item["category"],
                    value=val_dec,
                    formatted_value=fmt,
                    percentage_of_total=share,
                    count=item["orders"],
                    secondary_value=item["profit"],
                    metadata={
                        "units": item["units"],
                        "margin_pct": item["margin_pct"],
                        "cogs": float(item["cogs"]),
                        "revenue": float(item["revenue"]),
                    },
                )
            )

        return BreakdownResult(
            dimension="category",
            metric=active_metric_key,
            total_value=total_rev,
            items=items,
        )
