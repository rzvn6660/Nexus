"""Dimensional segmentation and categorical distribution analysis."""

from decimal import Decimal, ROUND_HALF_UP
from typing import List, Dict, Any, Optional
from sqlalchemy import select, func, and_
from sqlalchemy.orm import Session
from app.models.customer import Customer
from app.models.sale import Sale
from app.analytics.core.context import AnalysisContext
from app.analytics.core.models import BreakdownItem, BreakdownResult


class SegmentationAnalyzer:
    """Computes breakdowns across customer segments, geographic cities, and retail channels."""

    @classmethod
    def get_customer_segment_breakdown(
        cls, session: Session, context: Optional[AnalysisContext] = None
    ) -> BreakdownResult:
        """
        Break down revenue, orders, and customer count by customer segment
        (e.g. Retail, Wholesale, Corporate, VIP).
        """
        stmt = (
            select(
                Customer.customer_segment.label("segment"),
                func.count(func.distinct(Customer.id)).label("customer_count"),
                func.count(Sale.id).label("order_count"),
                func.coalesce(
                    func.sum(Sale.subtotal - Sale.discount_amount), Decimal("0.00")
                ).label("revenue"),
            )
            .join(Sale, Customer.id == Sale.customer_id)
            .where(Sale.status.in_(["completed", "shipped"]))
            .group_by(Customer.customer_segment)
        )

        if context and context.date_from:
            stmt = stmt.where(Sale.transaction_date >= context.date_from)
        if context and context.date_to:
            stmt = stmt.where(Sale.transaction_date <= context.date_to)

        rows = session.execute(stmt).all()

        total_rev = Decimal("0.00")
        raw_items = []
        for r in rows:
            rev = Decimal(str(r.revenue)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            total_rev += rev
            raw_items.append(
                {
                    "segment": r.segment,
                    "revenue": rev,
                    "orders": int(r.order_count),
                    "customers": int(r.customer_count),
                }
            )

        raw_items.sort(key=lambda x: x["revenue"], reverse=True)

        items: List[BreakdownItem] = []
        for item in raw_items:
            pct = (
                round(float((item["revenue"] / total_rev) * Decimal("100.0")), 2)
                if total_rev > 0
                else 0.0
            )
            items.append(
                BreakdownItem(
                    key=item["segment"],
                    label=item["segment"],
                    value=item["revenue"],
                    formatted_value=f"${item['revenue']:,.2f}",
                    percentage_of_total=pct,
                    count=item["orders"],
                    metadata={"customer_count": item["customers"]},
                )
            )

        return BreakdownResult(
            dimension="customer_segment",
            metric="revenue",
            total_value=total_rev,
            items=items,
        )

    @classmethod
    def get_city_breakdown(
        cls, session: Session, context: Optional[AnalysisContext] = None, limit: int = 10
    ) -> BreakdownResult:
        """Break down revenue and customer activity by customer geographic city."""
        stmt = (
            select(
                Customer.city.label("city"),
                func.count(func.distinct(Customer.id)).label("customer_count"),
                func.count(Sale.id).label("order_count"),
                func.coalesce(
                    func.sum(Sale.subtotal - Sale.discount_amount), Decimal("0.00")
                ).label("revenue"),
            )
            .join(Sale, Customer.id == Sale.customer_id)
            .where(Sale.status.in_(["completed", "shipped"]))
            .group_by(Customer.city)
        )

        if context and context.date_from:
            stmt = stmt.where(Sale.transaction_date >= context.date_from)
        if context and context.date_to:
            stmt = stmt.where(Sale.transaction_date <= context.date_to)

        rows = session.execute(stmt).all()

        total_rev = Decimal("0.00")
        raw_items = []
        for r in rows:
            rev = Decimal(str(r.revenue)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            total_rev += rev
            raw_items.append(
                {
                    "city": r.city,
                    "revenue": rev,
                    "orders": int(r.order_count),
                    "customers": int(r.customer_count),
                }
            )

        raw_items.sort(key=lambda x: x["revenue"], reverse=True)

        items: List[BreakdownItem] = []
        for item in raw_items[:limit]:
            pct = (
                round(float((item["revenue"] / total_rev) * Decimal("100.0")), 2)
                if total_rev > 0
                else 0.0
            )
            items.append(
                BreakdownItem(
                    key=item["city"],
                    label=item["city"],
                    value=item["revenue"],
                    formatted_value=f"${item['revenue']:,.2f}",
                    percentage_of_total=pct,
                    count=item["orders"],
                    metadata={"customer_count": item["customers"]},
                )
            )

        return BreakdownResult(
            dimension="city",
            metric="revenue",
            total_value=total_rev,
            items=items,
        )
