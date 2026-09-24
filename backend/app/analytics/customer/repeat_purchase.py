"""Deterministic repeat-purchase and customer order frequency analytics."""

from typing import Dict, Any, Optional
from sqlalchemy import select, func, and_
from sqlalchemy.orm import Session
from app.models.sale import Sale
from app.analytics.core.context import AnalysisContext
from app.analytics.core.models import RepeatPurchaseResult


class RepeatPurchaseAnalyzer:
    """Calculates customer repeat order dynamics and purchase frequency distributions."""

    @classmethod
    def evaluate(
        cls, session: Session, context: Optional[AnalysisContext] = None
    ) -> RepeatPurchaseResult:
        """
        Evaluate customer repeat purchase rate and distribution of completed transaction counts.
        """
        stmt = (
            select(
                Sale.customer_id.label("customer_id"),
                func.count(Sale.id).label("order_count"),
            )
            .where(Sale.status.in_(["completed", "shipped"]))
            .group_by(Sale.customer_id)
        )

        if context and context.date_from:
            stmt = stmt.where(Sale.transaction_date >= context.date_from)
        if context and context.date_to:
            stmt = stmt.where(Sale.transaction_date <= context.date_to)
        if context and context.customer_ids:
            stmt = stmt.where(Sale.customer_id.in_(context.customer_ids))

        rows = session.execute(stmt).all()

        total_customers = len(rows)
        if total_customers == 0:
            return RepeatPurchaseResult(
                total_customers_with_orders=0,
                one_time_customers=0,
                repeat_customers=0,
                repeat_purchase_rate=0.0,
                average_orders_per_customer=0.0,
                orders_distribution={"1": 0, "2": 0, "3-5": 0, "6+": 0},
            )

        one_time = 0
        repeat = 0
        total_orders = 0
        dist = {"1": 0, "2": 0, "3-5": 0, "6+": 0}

        for r in rows:
            cnt = int(r.order_count)
            total_orders += cnt
            if cnt == 1:
                one_time += 1
                dist["1"] += 1
            else:
                repeat += 1
                if cnt == 2:
                    dist["2"] += 1
                elif 3 <= cnt <= 5:
                    dist["3-5"] += 1
                else:
                    dist["6+"] += 1

        repeat_rate = round((repeat / total_customers) * 100.0, 2)
        avg_orders = round(total_orders / total_customers, 2)

        return RepeatPurchaseResult(
            total_customers_with_orders=total_customers,
            one_time_customers=one_time,
            repeat_customers=repeat,
            repeat_purchase_rate=repeat_rate,
            average_orders_per_customer=avg_orders,
            orders_distribution=dist,
        )
