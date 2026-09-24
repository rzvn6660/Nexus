"""Deterministic RFM (Recency, Frequency, Monetary) segmentation analysis."""

from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import List, Dict, Any, Optional
import pandas as pd
from pydantic import BaseModel, Field
from sqlalchemy import select, func, and_
from sqlalchemy.orm import Session
from app.models.customer import Customer
from app.models.sale import Sale
from app.analytics.core.context import AnalysisContext
from app.analytics.core.models import CustomerRFMRecord


class RFMAnalysisSummary(BaseModel):
    """Overall summary of RFM segmentation across the customer base."""
    total_customers_analyzed: int
    as_of_date: str
    quantile_bins: int
    segment_counts: Dict[str, int]
    top_customers: List[CustomerRFMRecord]
    methodology: str
    limitations: List[str]


def _assign_segment(r: int, f: int, m: int) -> str:
    """
    Deterministic rule-based customer segment assignment based on 1-5 scores.
    Scores: 5 is best (most recent, highest frequency, highest spend).
    """
    if r >= 4 and f >= 4 and m >= 4:
        return "Champions"
    if r >= 3 and f >= 3:
        return "Loyal Customers"
    if r >= 4 and f <= 2:
        return "Recent Customers"
    if r >= 3 and f <= 2 and m >= 3:
        return "Potential Loyalists"
    if r <= 2 and f >= 3 and m >= 3:
        return "At Risk"
    if r <= 2 and f >= 4:
        return "Can't Lose Them"
    if r <= 2 and f <= 2 and m >= 3:
        return "About to Sleep"
    if r <= 2 and f <= 2 and m <= 2:
        return "Hibernating"
    return "Promising"


class RFMAnalyzer:
    """Calculates deterministic RFM metrics and quantile scores for customers."""

    @classmethod
    def evaluate(
        cls,
        session: Session,
        context: Optional[AnalysisContext] = None,
        as_of_date: Optional[datetime] = None,
        quantile_bins: int = 5,
        limit_top: int = 50,
    ) -> RFMAnalysisSummary:
        """
        Compute Recency (days), Frequency (count), and Monetary (sum) for each customer.
        Assigns 1-N quantile scores.
        """
        ref_date = as_of_date or datetime.now(timezone.utc)
        if ref_date.tzinfo is None:
            ref_date = ref_date.replace(tzinfo=timezone.utc)

        # Aggregate customer orders
        stmt = (
            select(
                Customer.id.label("customer_id"),
                Customer.customer_code.label("customer_code"),
                Customer.name.label("name"),
                Customer.customer_segment.label("segment"),
                func.max(Sale.transaction_date).label("last_purchase_date"),
                func.count(Sale.id).label("frequency"),
                func.coalesce(
                    func.sum(Sale.subtotal - Sale.discount_amount), Decimal("0.00")
                ).label("monetary"),
            )
            .join(Sale, Customer.id == Sale.customer_id)
            .where(Sale.status.in_(["completed", "shipped"]))
            .group_by(Customer.id)
        )

        if context and context.date_from:
            stmt = stmt.where(Sale.transaction_date >= context.date_from)
        if context and context.date_to:
            stmt = stmt.where(Sale.transaction_date <= context.date_to)
        if context and context.customer_segments:
            stmt = stmt.where(Customer.customer_segment.in_(context.customer_segments))

        rows = session.execute(stmt).all()

        if not rows:
            return RFMAnalysisSummary(
                total_customers_analyzed=0,
                as_of_date=ref_date.isoformat(),
                quantile_bins=quantile_bins,
                segment_counts={},
                top_customers=[],
                methodology="Quantile ranking (1-5) on Recency, Frequency, and Monetary",
                limitations=["No completed transactions found in evaluation scope."],
            )

        data = []
        for r in rows:
            last_date = r.last_purchase_date
            if last_date.tzinfo is None:
                last_date = last_date.replace(tzinfo=timezone.utc)
            recency_days = max(int((ref_date - last_date).total_seconds() / 86400.0), 0)
            data.append(
                {
                    "customer_id": r.customer_id,
                    "customer_code": r.customer_code,
                    "name": r.name,
                    "segment": r.segment,
                    "recency_days": recency_days,
                    "frequency": int(r.frequency),
                    "monetary": float(Decimal(str(r.monetary))),
                }
            )

        df = pd.DataFrame(data)

        # Quantile binning:
        # Recency: lower days is better -> reverse score (lowest recency gets score 5)
        # Frequency: higher is better -> score 5
        # Monetary: higher is better -> score 5
        # Use pandas qcut with rank(method='first') to handle ties cleanly
        df["r_score"] = pd.qcut(
            df["recency_days"].rank(method="first", ascending=False),
            q=quantile_bins,
            labels=range(1, quantile_bins + 1),
        ).astype(int)

        df["f_score"] = pd.qcut(
            df["frequency"].rank(method="first"),
            q=quantile_bins,
            labels=range(1, quantile_bins + 1),
        ).astype(int)

        df["m_score"] = pd.qcut(
            df["monetary"].rank(method="first"),
            q=quantile_bins,
            labels=range(1, quantile_bins + 1),
        ).astype(int)

        df["rfm_score"] = (
            df["r_score"].astype(str) + df["f_score"].astype(str) + df["m_score"].astype(str)
        )
        df["rfm_segment"] = df.apply(
            lambda row: _assign_segment(row["r_score"], row["f_score"], row["m_score"]),
            axis=1,
        )

        segment_counts = df["rfm_segment"].value_counts().to_dict()

        # Sort by Monetary desc, then Frequency desc, then Recency asc
        df = df.sort_values(
            by=["monetary", "frequency", "recency_days"],
            ascending=[False, False, True],
        )

        top_records: List[CustomerRFMRecord] = []
        for _, row in df.head(limit_top).iterrows():
            top_records.append(
                CustomerRFMRecord(
                    customer_id=int(row["customer_id"]),
                    customer_code=str(row["customer_code"]),
                    name=str(row["name"]),
                    segment=str(row["segment"]),
                    recency_days=int(row["recency_days"]),
                    frequency_orders=int(row["frequency"]),
                    monetary_revenue=Decimal(str(round(row["monetary"], 2))),
                    r_score=int(row["r_score"]),
                    f_score=int(row["f_score"]),
                    m_score=int(row["m_score"]),
                    rfm_score=str(row["rfm_score"]),
                    rfm_segment=str(row["rfm_segment"]),
                )
            )

        return RFMAnalysisSummary(
            total_customers_analyzed=len(df),
            as_of_date=ref_date.isoformat(),
            quantile_bins=quantile_bins,
            segment_counts=segment_counts,
            top_customers=top_records,
            methodology=(
                f"Ranked customers into {quantile_bins} quantiles across Recency (days since last purchase), "
                f"Frequency (distinct orders), and Monetary value (net revenue). Recency is inverted so that "
                f"most recent customers receive higher scores."
            ),
            limitations=[
                "RFM is an analytical segmentation tool based on past transaction patterns; it does NOT predict future churn probability.",
                "Quantile boundaries are relative to the active dataset distribution.",
            ],
        )
