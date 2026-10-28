"""Deterministic customer purchase cadence and heuristic inactivity analyzer.

Computes empirical inter-purchase intervals (IPI), elapsed recency, dynamic cadence
ratios, and provisional risk tiers. This is a heuristic operational indicator,
NOT a calibrated churn-probability model.
"""

from collections import defaultdict
from datetime import UTC, date, datetime
from enum import Enum
from typing import Any, Literal

import numpy as np
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analytics.core.context import AnalysisContext
from app.models.customer import Customer
from app.models.sale import Sale


class CadenceRiskTier(str, Enum):
    """Heuristic inactivity risk tiers based on purchase cadence ratio."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"
    INSUFFICIENT_HISTORY = "insufficient_history"


class CadenceExplanation(BaseModel):
    """Structured explanation of the customer's cadence assessment."""

    summary: str = Field(description="Human-readable assessment summary.")
    provisional_notice: str = Field(
        default=(
            "Heuristic purchase cadence indicator based on observed transaction intervals; "
            "provisional non-calibrated metric; does not assert definitive customer churn."
        ),
        description="Mandatory disclaimer distinguishing heuristic cadence from calibrated churn probability.",
    )
    cadence_source: str = Field(
        description="Source of baseline cadence: 'individual', 'segment_fallback', 'insufficient_history', or 'no_purchases'."
    )
    risk_drivers: list[str] = Field(
        default_factory=list,
        description="Key factual factors contributing to the risk tier assignment.",
    )


class CustomerCadenceRecord(BaseModel):
    """Customer purchase cadence metrics and heuristic risk tier."""

    customer_id: int
    customer_code: str
    name: str
    customer_segment: str | None = None
    eligible_order_count: int = Field(
        description="Count of distinct eligible completed orders at or before the cutoff date."
    )
    distinct_purchase_dates_count: int = Field(
        default=0,
        description="Count of distinct purchase event timestamps at or before cutoff.",
    )
    is_repeat_buyer: bool = Field(
        default=False,
        description="Whether customer has >= 2 distinct completed purchase events separated in time.",
    )
    mean_ipi_days: float | None = Field(
        default=None,
        description="Arithmetic mean inter-purchase interval in days, where mathematically defined.",
    )
    std_ipi_days: float | None = Field(
        default=None,
        description="Sample standard deviation (ddof=1) of inter-purchase intervals in days, where mathematically defined.",
    )
    median_ipi_days: float | None = Field(
        default=None,
        description="Median inter-purchase interval in days, where mathematically defined.",
    )
    last_purchase_date: datetime | None = Field(
        default=None,
        description="Timestamp (UTC) of the last eligible purchase at or before the cutoff date.",
    )
    days_since_last_purchase: float | None = Field(
        default=None,
        description="Elapsed days between the last eligible purchase and the evaluation cutoff date.",
    )
    baseline_cadence_days: float | None = Field(
        default=None,
        description="Expected inter-purchase interval used for cadence ratio evaluation (individual or segment fallback).",
    )
    cadence_source: str = Field(
        description="Source of the baseline cadence: 'individual', 'segment_fallback', 'insufficient_history', or 'no_purchases'."
    )
    cadence_ratio: float | None = Field(
        default=None,
        description="Ratio of elapsed days since last purchase to baseline cadence (recency / baseline_cadence).",
    )
    risk_tier: CadenceRiskTier = Field(
        description="Heuristic inactivity tier: low, medium, high, critical, or insufficient_history."
    )
    explanation: CadenceExplanation = Field(
        description="Structured explanation and factual drivers of the assignment."
    )


class CadenceConfig(BaseModel):
    """Configurable thresholds and operational parameters for customer cadence evaluation."""

    min_orders_for_individual_cadence: int = Field(
        default=2,
        ge=2,
        description="Minimum completed orders required to compute an individual cadence without fallback.",
    )
    use_segment_fallback: bool = Field(
        default=False,
        description=(
            "Whether to use segment-level median cadence for eligible repeat customers with "
            "insufficient individual history (e.g. min_orders_for_individual_cadence > 2). "
            "Never applies to one-time buyers."
        ),
    )
    min_segment_customers: int = Field(
        default=3,
        ge=1,
        description="Minimum number of repeat customers required in a segment to establish a valid fallback cadence.",
    )
    cadence_statistic: Literal["median", "mean"] = Field(
        default="median", description="Statistic used for baseline cadence: 'median' or 'mean'."
    )
    low_threshold: float = Field(
        default=1.25,
        gt=0.0,
        description="Cadence ratio upper bound for LOW risk tier (ratio < low_threshold).",
    )
    medium_threshold: float = Field(
        default=2.0,
        gt=0.0,
        description="Cadence ratio upper bound for MEDIUM risk tier (low_threshold <= ratio < medium_threshold).",
    )
    high_threshold: float = Field(
        default=3.0,
        gt=0.0,
        description="Cadence ratio upper bound for HIGH risk tier. Ratios >= this are CRITICAL.",
    )
    eligible_statuses: list[str] = Field(
        default_factory=lambda: ["completed", "shipped"],
        description="Eligible completed sale statuses. Excludes pending, cancelled, refunded.",
    )

    @model_validator(mode="after")
    def validate_thresholds(self) -> "CadenceConfig":
        if not (self.low_threshold < self.medium_threshold < self.high_threshold):
            raise ValueError(
                f"Cadence thresholds must satisfy low < medium < high, got: "
                f"low={self.low_threshold}, medium={self.medium_threshold}, high={self.high_threshold}"
            )
        return self


class CustomerCadenceSummary(BaseModel):
    """Overall summary of customer purchase cadence analysis across the evaluated cohort."""

    as_of_date: str = Field(description="ISO-8601 UTC timestamp of evaluation cutoff.")
    business_id: str | None = Field(default=None, description="Tenant business workspace boundary.")
    total_customers_evaluated: int
    customers_scored: int
    insufficient_history_count: int
    repeat_buyers_count: int = 0
    one_time_buyers_count: int = 0
    risk_tier_counts: dict[str, int]
    segment_fallbacks_used: int
    segment_baselines: dict[str, float | None]
    records: list[CustomerCadenceRecord]
    methodology: str = Field(
        default=(
            "Deterministic inter-purchase interval (IPI) cadence analysis comparing "
            "elapsed days since last purchase against customer median IPI or segment fallback for eligible repeat buyers."
        )
    )
    limitations: list[str] = Field(
        default_factory=lambda: [
            "Heuristic purchase cadence indicator based strictly on historical order timestamps; does not represent calibrated churn probability.",
            "Non-contractual retail transactions are right-censored; absence of orders does not verify permanent account cancellation.",
            "Single-purchase customers (fewer than 2 distinct purchases) are excluded from cadence-based churn risk tiers and classified as insufficient history.",
            "Seasonal purchasing cycles, holiday demand spikes, and external economic shifts may distort regular inter-purchase cadence.",
        ]
    )


class CustomerCadenceAnalyzer:
    """Calculates deterministic customer purchase cadence metrics and heuristic inactivity tiers."""

    @classmethod
    def evaluate(
        cls,
        session: Session,
        context: AnalysisContext | None = None,
        as_of_date: datetime | date | None = None,
        config: CadenceConfig | None = None,
    ) -> CustomerCadenceSummary:
        """
        Evaluate customer purchase cadence and inactivity risk across the cohort.

        Parameters:
            session: Active SQLAlchemy database session.
            context: Standard AnalysisContext specifying tenant boundary, customer filters, etc.
            as_of_date: Evaluation cutoff timestamp. Defaults to context.date_to or current UTC time.
            config: Operational thresholds and fallback settings. Defaults to standard CadenceConfig.
        """
        # 1. Resolve cutoff timestamp (UTC)
        if as_of_date is not None:
            if isinstance(as_of_date, datetime):
                ref_date = (
                    as_of_date if as_of_date.tzinfo is not None else as_of_date.replace(tzinfo=UTC)
                )
                ref_date = ref_date.astimezone(UTC)
            elif isinstance(as_of_date, date):
                # An as_of_date specified as a calendar date includes all transactions occurring on that date
                ref_date = datetime.combine(
                    as_of_date, datetime.max.time().replace(microsecond=0), tzinfo=UTC
                )
            else:
                raise ValueError(f"Invalid as_of_date type: {type(as_of_date)}")
        elif context and context.date_to is not None:
            ref_date = (
                context.date_to
                if context.date_to.tzinfo is not None
                else context.date_to.replace(tzinfo=UTC)
            )
            ref_date = ref_date.astimezone(UTC)
        else:
            ref_date = datetime.now(UTC)

        # 2. Resolve configuration and valid purchase statuses
        cfg = config or CadenceConfig()
        statuses = context.statuses if (context and context.statuses) else cfg.eligible_statuses

        # 3. Query customers in scope (strictly scoped to tenant and acquired at/before cutoff)
        cust_stmt = select(
            Customer.id,
            Customer.customer_code,
            Customer.name,
            Customer.customer_segment,
            Customer.business_id,
        ).where(Customer.acquisition_date <= ref_date.date())

        if context and context.business_id:
            cust_stmt = cust_stmt.where(Customer.business_id == context.business_id)
        if context and context.customer_ids:
            cust_stmt = cust_stmt.where(Customer.id.in_(context.customer_ids))
        if context and context.customer_segments:
            cust_stmt = cust_stmt.where(Customer.customer_segment.in_(context.customer_segments))
        cust_stmt = cust_stmt.order_by(Customer.id.asc())

        cust_rows = session.execute(cust_stmt).all()

        if not cust_rows:
            return CustomerCadenceSummary(
                as_of_date=ref_date.isoformat(),
                business_id=context.business_id if context else None,
                total_customers_evaluated=0,
                customers_scored=0,
                insufficient_history_count=0,
                risk_tier_counts={tier.value: 0 for tier in CadenceRiskTier},
                segment_fallbacks_used=0,
                segment_baselines={},
                records=[],
            )

        # 4. Query distinct eligible sales at or before cutoff
        sale_stmt = (
            select(
                Sale.id,
                Sale.customer_id,
                Sale.transaction_date,
                Sale.status,
                Sale.business_id,
            )
            .join(Customer, Customer.id == Sale.customer_id)
            .where(
                Sale.status.in_(statuses),
                Sale.transaction_date <= ref_date,
            )
        )
        if context and context.business_id:
            sale_stmt = sale_stmt.where(
                Sale.business_id == context.business_id,
                Customer.business_id == context.business_id,
            )
        if context and context.date_from:
            sale_stmt = sale_stmt.where(Sale.transaction_date >= context.date_from)
        if context and context.customer_ids:
            sale_stmt = sale_stmt.where(Customer.id.in_(context.customer_ids))
        if context and context.customer_segments:
            sale_stmt = sale_stmt.where(Customer.customer_segment.in_(context.customer_segments))

        sale_stmt = sale_stmt.order_by(
            Sale.customer_id.asc(),
            Sale.transaction_date.asc(),
            Sale.id.asc(),
        )

        sale_rows = session.execute(sale_stmt).all()

        # 5. Group distinct completed sales per customer
        customer_txns: dict[int, list[datetime]] = {c.id: [] for c in cust_rows}
        for s in sale_rows:
            t = s.transaction_date
            if t.tzinfo is None:
                t = t.replace(tzinfo=UTC)
            else:
                t = t.astimezone(UTC)
            if s.customer_id in customer_txns:
                customer_txns[s.customer_id].append(t)

        # 6. First pass: compute individual intervals & cadences
        customer_metrics: dict[int, dict[str, Any]] = {}
        repeat_count = 0
        one_time_count = 0

        for c in cust_rows:
            tx_dates = customer_txns[c.id]
            order_count = len(tx_dates)
            distinct_dates_count = len(set(tx_dates))

            if distinct_dates_count >= 2:
                repeat_count += 1
            elif order_count == 1:
                one_time_count += 1

            if order_count >= cfg.min_orders_for_individual_cadence:
                # Interval differences in floating-point days
                intervals = [
                    (tx_dates[i + 1] - tx_dates[i]).total_seconds() / 86400.0
                    for i in range(order_count - 1)
                ]
                mean_ipi = round(float(np.mean(intervals)), 2)
                median_ipi = round(float(np.median(intervals)), 2)
                std_ipi = (
                    round(float(np.std(intervals, ddof=1)), 2) if len(intervals) >= 2 else None
                )

                chosen_stat = median_ipi if cfg.cadence_statistic == "median" else mean_ipi
                indiv_cadence = (
                    chosen_stat
                    if (chosen_stat > 0.0 and distinct_dates_count >= 2)
                    else None
                )
            else:
                mean_ipi = None
                std_ipi = None
                median_ipi = None
                indiv_cadence = None

            customer_metrics[c.id] = {
                "order_count": order_count,
                "distinct_dates_count": distinct_dates_count,
                "mean_ipi": mean_ipi,
                "std_ipi": std_ipi,
                "median_ipi": median_ipi,
                "indiv_cadence": indiv_cadence,
                "last_date": tx_dates[-1] if order_count > 0 else None,
            }

        # 7. Compute segment fallbacks across repeat customers with positive individual cadence
        segment_baselines: dict[str, float | None] = {}
        if cfg.use_segment_fallback:
            needed_segments = {c.customer_segment for c in cust_rows if c.customer_segment}

            # If evaluating full cohort/business without customer_ids restriction, compute directly in-memory
            if not (context and context.customer_ids):
                segment_cadences: dict[str, list[float]] = defaultdict(list)
                for c in cust_rows:
                    seg = c.customer_segment
                    cad = customer_metrics[c.id]["indiv_cadence"]
                    if seg and cad is not None and cad > 0.0:
                        segment_cadences[seg].append(cad)

                for seg in needed_segments:
                    cad_list = segment_cadences.get(seg, [])
                    if len(cad_list) >= cfg.min_segment_customers:
                        stat_val = (
                            float(np.median(cad_list))
                            if cfg.cadence_statistic == "median"
                            else float(np.mean(cad_list))
                        )
                        segment_baselines[seg] = round(stat_val, 2)
                    else:
                        segment_baselines[seg] = None
            else:
                # When customer_ids filter is provided, resolve segment baseline from the authorized business's repeat customers
                seg_cust_stmt = select(Customer.id, Customer.customer_segment).where(
                    Customer.customer_segment.in_(needed_segments),
                    Customer.acquisition_date <= ref_date.date(),
                )
                if context and context.business_id:
                    seg_cust_stmt = seg_cust_stmt.where(Customer.business_id == context.business_id)

                seg_custs = session.execute(seg_cust_stmt).all()
                seg_cust_map = {sc.id: sc.customer_segment for sc in seg_custs}

                if seg_cust_map:
                    seg_sales_stmt = (
                        select(Sale.customer_id, Sale.transaction_date)
                        .join(Customer, Customer.id == Sale.customer_id)
                        .where(
                            Sale.status.in_(statuses),
                            Sale.transaction_date <= ref_date,
                            Customer.id.in_(list(seg_cust_map.keys())),
                        )
                        .order_by(
                            Sale.customer_id.asc(), Sale.transaction_date.asc(), Sale.id.asc()
                        )
                    )
                    if context and context.business_id:
                        seg_sales_stmt = seg_sales_stmt.where(
                            Sale.business_id == context.business_id,
                            Customer.business_id == context.business_id,
                        )
                    if context and context.date_from:
                        seg_sales_stmt = seg_sales_stmt.where(
                            Sale.transaction_date >= context.date_from
                        )

                    seg_sales_rows = session.execute(seg_sales_stmt).all()
                    seg_txns: dict[int, list[datetime]] = defaultdict(list)
                    for row in seg_sales_rows:
                        t = row.transaction_date
                        t = t.replace(tzinfo=UTC) if t.tzinfo is None else t.astimezone(UTC)
                        seg_txns[row.customer_id].append(t)

                    segment_cadences = defaultdict(list)
                    for cid, cseg in seg_cust_map.items():
                        tx_list = seg_txns[cid]
                        if len(tx_list) >= cfg.min_orders_for_individual_cadence and len(set(tx_list)) >= 2:
                            intervals = [
                                (tx_list[i + 1] - tx_list[i]).total_seconds() / 86400.0
                                for i in range(len(tx_list) - 1)
                            ]
                            c_stat = (
                                float(np.median(intervals))
                                if cfg.cadence_statistic == "median"
                                else float(np.mean(intervals))
                            )
                            if c_stat > 0.0:
                                segment_cadences[cseg].append(c_stat)

                    for seg in needed_segments:
                        cad_list = segment_cadences.get(seg, [])
                        if len(cad_list) >= cfg.min_segment_customers:
                            stat_val = (
                                float(np.median(cad_list))
                                if cfg.cadence_statistic == "median"
                                else float(np.mean(cad_list))
                            )
                            segment_baselines[seg] = round(stat_val, 2)
                        else:
                            segment_baselines[seg] = None
                else:
                    for seg in needed_segments:
                        segment_baselines[seg] = None

        # 8. Second pass: evaluate risk tiers and build records
        records: list[CustomerCadenceRecord] = []
        fallbacks_used = 0

        for c in cust_rows:
            metrics = customer_metrics[c.id]
            order_count = metrics["order_count"]
            distinct_dates_count = metrics["distinct_dates_count"]
            last_date = metrics["last_date"]
            indiv_cadence = metrics["indiv_cadence"]
            seg = c.customer_segment

            is_repeat_buyer = (order_count >= 2 and distinct_dates_count >= 2)

            if order_count == 0:
                rec = CustomerCadenceRecord(
                    customer_id=c.id,
                    customer_code=c.customer_code,
                    name=c.name,
                    customer_segment=seg,
                    eligible_order_count=0,
                    distinct_purchase_dates_count=0,
                    is_repeat_buyer=False,
                    mean_ipi_days=None,
                    std_ipi_days=None,
                    median_ipi_days=None,
                    last_purchase_date=None,
                    days_since_last_purchase=None,
                    baseline_cadence_days=None,
                    cadence_source="no_purchases",
                    cadence_ratio=None,
                    risk_tier=CadenceRiskTier.INSUFFICIENT_HISTORY,
                    explanation=CadenceExplanation(
                        summary=f"Customer '{c.customer_code}' has no eligible completed purchases recorded at or before cutoff date.",
                        cadence_source="no_purchases",
                        risk_drivers=["Zero completed purchases found in evaluation window."],
                    ),
                )
                records.append(rec)
                continue

            # Elapsed days since last purchase (strictly non-negative)
            recency_days = round(max(0.0, (ref_date - last_date).total_seconds() / 86400.0), 2)

            # Determine baseline cadence:
            # Segment fallback is strictly restricted to eligible repeat buyers (>= 2 distinct purchases).
            if indiv_cadence is not None and indiv_cadence > 0.0:
                baseline_cadence = indiv_cadence
                source = "individual"
            elif is_repeat_buyer and cfg.use_segment_fallback and seg and segment_baselines.get(seg) is not None:
                baseline_cadence = segment_baselines[seg]
                source = "segment_fallback"
                fallbacks_used += 1
            else:
                baseline_cadence = None
                source = "insufficient_history"

            # Determine ratio and risk tier
            if baseline_cadence is not None and baseline_cadence > 0.0:
                ratio = round(recency_days / baseline_cadence, 4)
                drivers: list[str] = []

                if source == "individual":
                    drivers.append(
                        f"Evaluated against individual {cfg.cadence_statistic} cadence of {baseline_cadence:.2f} days "
                        f"across {order_count} completed orders."
                    )
                else:
                    drivers.append(
                        f"Customer has {order_count} completed orders; evaluated against '{seg}' segment "
                        f"{cfg.cadence_statistic} cadence fallback of {baseline_cadence:.2f} days."
                    )

                drivers.append(
                    f"Elapsed recency is {recency_days:.2f} days (cadence ratio: {ratio:.2f}x)."
                )

                if ratio < cfg.low_threshold:
                    tier = CadenceRiskTier.LOW
                    drivers.append(
                        f"Cadence ratio ({ratio:.2f}x) is below low risk threshold (< {cfg.low_threshold:.2f}x)."
                    )
                    summary = (
                        f"Customer '{c.customer_code}' is within expected purchase cadence "
                        f"({recency_days:.1f} days elapsed vs {baseline_cadence:.1f} days baseline, ratio {ratio:.2f}x)."
                    )
                elif ratio < cfg.medium_threshold:
                    tier = CadenceRiskTier.MEDIUM
                    drivers.append(
                        f"Cadence ratio ({ratio:.2f}x) exceeds normal cycle but is below medium threshold (< {cfg.medium_threshold:.2f}x)."
                    )
                    summary = (
                        f"Customer '{c.customer_code}' is moderately overdue "
                        f"({recency_days:.1f} days elapsed vs {baseline_cadence:.1f} days baseline, ratio {ratio:.2f}x)."
                    )
                elif ratio < cfg.high_threshold:
                    tier = CadenceRiskTier.HIGH
                    drivers.append(
                        f"Cadence ratio ({ratio:.2f}x) exceeds medium threshold (>= {cfg.medium_threshold:.2f}x)."
                    )
                    summary = (
                        f"Customer '{c.customer_code}' is significantly overdue "
                        f"({recency_days:.1f} days elapsed vs {baseline_cadence:.1f} days baseline, ratio {ratio:.2f}x)."
                    )
                else:
                    tier = CadenceRiskTier.CRITICAL
                    drivers.append(
                        f"Cadence ratio ({ratio:.2f}x) exceeds critical threshold (>= {cfg.high_threshold:.2f}x)."
                    )
                    summary = (
                        f"Customer '{c.customer_code}' is critically overdue "
                        f"({recency_days:.1f} days elapsed vs {baseline_cadence:.1f} days baseline, ratio {ratio:.2f}x)."
                    )

                explanation = CadenceExplanation(
                    summary=summary,
                    cadence_source=source,
                    risk_drivers=drivers,
                )
            else:
                ratio = None
                tier = CadenceRiskTier.INSUFFICIENT_HISTORY

                if order_count == 1:
                    drivers = [
                        "Customer has only 1 completed purchase recorded; minimum of 2 distinct completed purchase events required to establish repeat cadence.",
                        "Cadence-based churn risk is undefined for one-time buyers; customer cannot be evaluated with cadence ratio.",
                    ]
                    summary = (
                        f"Customer '{c.customer_code}' has only 1 purchase recorded; "
                        "insufficient repeat purchase history to estimate personal cadence or evaluate churn risk."
                    )
                elif distinct_dates_count < 2:
                    drivers = [
                        (
                            f"Customer has {order_count} purchase(s) but all occurred simultaneously (zero elapsed interval); "
                            "distinct inter-purchase cadence cannot be calculated."
                        ),
                    ]
                    summary = (
                        f"Customer '{c.customer_code}' has multiple purchases on the same timestamp; "
                        "insufficient temporal separation to establish cadence baseline."
                    )
                else:
                    drivers = [
                        f"Customer has {order_count} completed purchase(s); minimum required for individual cadence is {cfg.min_orders_for_individual_cadence}.",
                    ]
                    if not cfg.use_segment_fallback:
                        drivers.append("Segment-level fallback is disabled in configuration.")
                    elif not seg:
                        drivers.append("Customer has no assigned customer_segment for fallback.")
                    else:
                        drivers.append(
                            f"Segment '{seg}' lacks sufficient repeat customers (minimum {cfg.min_segment_customers} required) "
                            "to establish a reliable fallback cadence."
                        )
                    summary = (
                        f"Customer '{c.customer_code}' has insufficient repeat purchase history "
                        "to establish a reliable cadence baseline."
                    )

                explanation = CadenceExplanation(
                    summary=summary,
                    cadence_source="insufficient_history",
                    risk_drivers=drivers,
                )

            rec = CustomerCadenceRecord(
                customer_id=c.id,
                customer_code=c.customer_code,
                name=c.name,
                customer_segment=seg,
                eligible_order_count=order_count,
                distinct_purchase_dates_count=distinct_dates_count,
                is_repeat_buyer=is_repeat_buyer,
                mean_ipi_days=metrics["mean_ipi"],
                std_ipi_days=metrics["std_ipi"],
                median_ipi_days=metrics["median_ipi"],
                last_purchase_date=last_date,
                days_since_last_purchase=recency_days,
                baseline_cadence_days=baseline_cadence,
                cadence_source=source,
                cadence_ratio=ratio,
                risk_tier=tier,
                explanation=explanation,
            )
            records.append(rec)

        # 9. Aggregate cohort summary counts
        tier_counts = {t.value: 0 for t in CadenceRiskTier}
        scored_count = 0
        insufficient_count = 0
        for r in records:
            tier_counts[r.risk_tier.value] += 1
            if r.risk_tier == CadenceRiskTier.INSUFFICIENT_HISTORY:
                insufficient_count += 1
            else:
                scored_count += 1

        return CustomerCadenceSummary(
            as_of_date=ref_date.isoformat(),
            business_id=context.business_id if context else None,
            total_customers_evaluated=len(records),
            customers_scored=scored_count,
            insufficient_history_count=insufficient_count,
            repeat_buyers_count=repeat_count,
            one_time_buyers_count=one_time_count,
            risk_tier_counts=tier_counts,
            segment_fallbacks_used=fallbacks_used,
            segment_baselines=segment_baselines,
            records=records,
        )
