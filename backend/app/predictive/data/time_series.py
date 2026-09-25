"""Deterministic time-series preparation, frequency normalization, and aggregation."""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pandas as pd
from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from app.models.product import Product
from app.models.sale import Sale
from app.models.sale_item import SaleItem
from app.predictive.schemas import ForecastFrequency


class TimeSeriesPreparer:
    """
    Extracts transactional telemetry from the database, normalizes chronological
    spacing across daily/weekly/monthly frequencies, and constructs structured feature series.
    """

    def __init__(self, session: Session | None = None) -> None:
        self.session = session

    def prepare(
        self,
        target_metric: Any,
        frequency: Any = "monthly",
        entity_type: str | None = None,
        entity_id: str | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        min_observations: int = 4,
    ) -> tuple[pd.DataFrame, Any]:
        """Extract historical series and validate quality."""
        from app.predictive.data.quality import TimeSeriesQualityGate
        target_str = target_metric.value if hasattr(target_metric, "value") else str(target_metric)
        freq_str = frequency.value if hasattr(frequency, "value") else str(frequency)
        if self.session is None:
            raise ValueError("Database session required for prepare()")
        df = self.extract_series(
            session=self.session,
            target_metric=target_str,
            frequency=freq_str,
            entity_type=entity_type,
            entity_id=entity_id,
            date_from=date_from,
            date_to=date_to,
        )
        quality, _ = TimeSeriesQualityGate.evaluate(
            df=df,
            frequency=freq_str,
            min_observations=min_observations,
        )
        return df, quality

    @classmethod
    def extract_series(
        cls,
        session: Session,
        target_metric: str,
        frequency: str = "monthly",
        entity_type: str | None = None,
        entity_id: str | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
    ) -> pd.DataFrame:
        """
        Extract transactions, aggregate into continuous frequency buckets, and return DataFrame
        with columns: [period_label, period_start, period_end, value, is_zero].
        """
        # Formulate query
        stmt = (
            select(
                Sale.id.label("sale_id"),
                Sale.transaction_date.label("transaction_date"),
                Sale.status.label("status"),
                SaleItem.quantity.label("quantity"),
                SaleItem.line_total.label("line_total"),
                Product.sku.label("sku"),
                Product.name.label("product_name"),
                Product.category.label("category"),
            )
            .join(SaleItem, Sale.id == SaleItem.sale_id)
            .join(Product, SaleItem.product_id == Product.id)
            .where(Sale.status.in_(["completed", "shipped"]))
        )

        clauses = []
        if date_from:
            clauses.append(Sale.transaction_date >= date_from)
        if date_to:
            clauses.append(Sale.transaction_date <= date_to)

        # Entity filtering
        if entity_type == "product" and entity_id or target_metric in ("product_demand", "product_sales") and entity_id:
            clauses.append(Product.sku == entity_id)
        elif entity_type == "category" and entity_id:
            clauses.append(Product.category == entity_id)

        if clauses:
            stmt = stmt.where(and_(*clauses))

        rows = session.execute(stmt).all()

        if not rows:
            return pd.DataFrame(columns=["period_label", "period_start", "period_end", "value", "is_zero"])

        # Collect raw records
        data = []
        for r in rows:
            tx: datetime = r.transaction_date
            if tx.tzinfo is None:
                tx = tx.replace(tzinfo=UTC)
            rev = float(Decimal(str(r.line_total)))
            qty = int(r.quantity)
            data.append({
                "sale_id": r.sale_id,
                "date": tx,
                "revenue": rev,
                "units": qty,
            })

        raw_df = pd.DataFrame(data)
        raw_df["date"] = pd.to_datetime(raw_df["date"], utc=True)
        raw_df = raw_df.sort_values("date")

        # Determine target metric extraction
        metric_norm = target_metric.lower().strip()
        is_units = metric_norm in ("units", "units_sold", "product_demand", "quantity")
        is_orders = metric_norm in ("orders", "order_volume", "transactions")

        # Frequency normalization mapping
        freq_norm = frequency.lower().strip()
        if freq_norm in ("d", "daily", ForecastFrequency.DAILY.value):
            rule = "D"
            date_format = "%Y-%m-%d"
            start_norm = raw_df["date"].min().floor("D")
        elif freq_norm in ("w", "weekly", ForecastFrequency.WEEKLY.value):
            rule = "W-MON"
            date_format = "%Y-W%U"
            min_d = raw_df["date"].min()
            start_norm = (min_d - pd.Timedelta(days=min_d.weekday())).floor("D")
        else:
            rule = "MS"
            date_format = "%Y-%m"
            min_d = raw_df["date"].min()
            start_norm = pd.Timestamp(year=min_d.year, month=min_d.month, day=1, tz=UTC)

        # Determine overall timeline bounds
        max_date = raw_df["date"].max().ceil("D")

        # Generate continuous index
        complete_idx = pd.date_range(start=start_norm, end=max_date, freq=rule, tz=UTC)
        if len(complete_idx) == 0:
            complete_idx = pd.DatetimeIndex([start_norm])

        # Aggregate raw observations
        results = []
        for idx_start in complete_idx:
            if rule == "MS":
                # Month boundary
                next_month = (idx_start.month % 12) + 1
                next_year = idx_start.year + (1 if next_month == 1 else 0)
                idx_end = pd.Timestamp(year=next_year, month=next_month, day=1, tz=UTC) - pd.Timedelta(seconds=1)
                label = idx_start.strftime(date_format)
            elif rule == "W-MON":
                idx_end = idx_start + pd.Timedelta(days=6, hours=23, minutes=59, seconds=59)
                label = idx_start.strftime(date_format)
            else:  # Daily
                idx_end = idx_start + pd.Timedelta(hours=23, minutes=59, seconds=59)
                label = idx_start.strftime(date_format)

            sub = raw_df[(raw_df["date"] >= idx_start) & (raw_df["date"] <= idx_end)]
            if len(sub) > 0:
                if is_orders:
                    val = float(sub["sale_id"].nunique())
                elif is_units:
                    val = float(sub["units"].sum())
                else:
                    val = round(float(sub["revenue"].sum()), 2)
                is_zero = False
            else:
                val = 0.0
                is_zero = True

            results.append({
                "period_label": label,
                "period_start": idx_start.isoformat(),
                "period_end": idx_end.isoformat(),
                "value": val,
                "is_zero": is_zero,
            })

        out_df = pd.DataFrame(results)
        return out_df
