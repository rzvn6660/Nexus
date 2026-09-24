"""Deterministic time-series aggregation and temporal trend analysis."""

from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import List, Dict, Any, Optional
import pandas as pd
from sqlalchemy import select, and_
from sqlalchemy.orm import Session
from app.models.sale import Sale
from app.models.sale_item import SaleItem
from app.models.product import Product
from app.analytics.core.types import PeriodGranularity
from app.analytics.core.context import AnalysisContext
from app.analytics.core.models import (
    TimeSeriesPoint,
    TimeSeriesResult,
)


class TimeSeriesAnalyzer:
    """Aggregates business metrics across chronological intervals."""

    @classmethod
    def evaluate(
        cls,
        session: Session,
        context: AnalysisContext,
        metric: str = "revenue",
    ) -> TimeSeriesResult:
        """
        Aggregate transaction data into chronological buckets:
        daily, weekly, monthly, or quarterly.
        """
        # Fetch relevant sales records with line items and product costs
        stmt = (
            select(
                Sale.id.label("sale_id"),
                Sale.transaction_date.label("transaction_date"),
                Sale.status.label("status"),
                SaleItem.quantity.label("quantity"),
                SaleItem.line_total.label("line_total"),
                Product.unit_cost.label("unit_cost"),
            )
            .join(SaleItem, Sale.id == SaleItem.sale_id)
            .join(Product, SaleItem.product_id == Product.id)
            .where(Sale.status.in_(context.statuses if context.statuses else ["completed", "shipped"]))
        )

        clauses = []
        if context.date_from:
            clauses.append(Sale.transaction_date >= context.date_from)
        if context.date_to:
            clauses.append(Sale.transaction_date <= context.date_to)
        if context.product_ids:
            clauses.append(SaleItem.product_id.in_(context.product_ids))
        if context.categories:
            clauses.append(Product.category.in_(context.categories))
        if context.subcategories:
            clauses.append(Product.subcategory.in_(context.subcategories))
        if context.customer_ids:
            clauses.append(Sale.customer_id.in_(context.customer_ids))
        if clauses:
            stmt = stmt.where(and_(*clauses))

        rows = session.execute(stmt).all()

        if not rows:
            return TimeSeriesResult(
                metric=metric,
                granularity=context.granularity,
                points=[],
                total=Decimal("0.00"),
                average=Decimal("0.00"),
            )

        data = []
        for r in rows:
            tx: datetime = r.transaction_date
            if tx.tzinfo is None:
                tx = tx.replace(tzinfo=timezone.utc)
            rev = float(Decimal(str(r.line_total)))
            qty = int(r.quantity)
            cost = float(Decimal(str(r.unit_cost))) * qty
            profit = rev - cost

            data.append(
                {
                    "sale_id": r.sale_id,
                    "date": tx,
                    "revenue": rev,
                    "units": qty,
                    "cogs": cost,
                    "profit": profit,
                }
            )

        df = pd.DataFrame(data)
        df["date"] = pd.to_datetime(df["date"], utc=True)
        df = df.sort_values("date")

        # Map PeriodGranularity to pandas frequency string
        gran = context.granularity
        if gran == PeriodGranularity.DAILY:
            freq = "D"
            df["period_key"] = df["date"].dt.strftime("%Y-%m-%d")
        elif gran == PeriodGranularity.WEEKLY:
            freq = "W-MON"
            df["period_key"] = df["date"].dt.strftime("%Y-W%U")
        elif gran == PeriodGranularity.QUARTERLY:
            freq = "Q"
            df["period_key"] = df["date"].dt.to_period("Q").astype(str)
        else:  # MONTHLY default
            freq = "MS"
            df["period_key"] = df["date"].dt.strftime("%Y-%m")

        grouped = df.groupby("period_key")

        points: List[TimeSeriesPoint] = []
        metric_key = metric.lower()
        prior_val: Optional[float] = None
        running_total = Decimal("0.00")
        min_val: Optional[Decimal] = None
        max_val: Optional[Decimal] = None

        for period_key, group in grouped:
            orders = group["sale_id"].nunique()
            units = int(group["units"].sum())
            rev = round(group["revenue"].sum(), 2)
            profit = round(group["profit"].sum(), 2)
            cogs = round(group["cogs"].sum(), 2)

            if metric_key in ("profit", "gross_profit"):
                active_val = Decimal(str(profit))
                secondary_val = Decimal(str(cogs))
            elif metric_key in ("units", "units_sold"):
                active_val = Decimal(str(units))
                secondary_val = Decimal(str(rev))
            elif metric_key in ("orders", "order_count"):
                active_val = Decimal(str(orders))
                secondary_val = Decimal(str(rev))
            else:  # default revenue
                active_val = Decimal(str(rev))
                secondary_val = Decimal(str(profit))

            growth: Optional[float] = None
            f_val = float(active_val)
            if prior_val is not None:
                if prior_val != 0.0:
                    growth = round(((f_val - prior_val) / abs(prior_val)) * 100.0, 2)
                elif f_val == 0.0:
                    growth = 0.0
                else:
                    growth = None
            prior_val = f_val

            running_total += active_val
            if min_val is None or active_val < min_val:
                min_val = active_val
            if max_val is None or active_val > max_val:
                max_val = active_val

            p_start = group["date"].min().isoformat()
            p_end = group["date"].max().isoformat()

            points.append(
                TimeSeriesPoint(
                    period_start=p_start,
                    period_end=p_end,
                    period_label=str(period_key),
                    value=active_val,
                    secondary_value=secondary_val,
                    orders=orders,
                    units=units,
                    growth_rate=growth,
                )
            )

        avg_val = (
            (running_total / Decimal(len(points))).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
            if points
            else Decimal("0.00")
        )

        return TimeSeriesResult(
            metric=metric,
            granularity=context.granularity,
            points=points,
            total=running_total,
            average=avg_val,
            min_value=min_val,
            max_value=max_val,
        )
