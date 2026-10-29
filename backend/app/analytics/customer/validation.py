"""Historical validation and backtesting engine for customer purchase cadence heuristics.

Evaluates whether heuristic inactivity risk tiers (Low, Medium, High, Critical)
accurately identify customers who subsequently have no observed repeat purchases
during a defined forward outcome horizon.

This module validates empirical performance without asserting calibrated probabilities
or definitive permanent churn.
"""

from datetime import UTC, date, datetime, timedelta
from typing import Any

import numpy as np
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.analytics.core.context import AnalysisContext
from app.analytics.customer.cadence import (
    CadenceConfig,
    CadenceRiskTier,
    CustomerCadenceAnalyzer,
    CustomerCadenceSummary,
)
from app.models.customer import Customer
from app.models.sale import Sale
from app.models.tenant import IngestionJob


def compute_wilson_score_interval(
    k: int, n: int, confidence_z: float = 1.959964
) -> tuple[float | None, float | None]:
    """
    Compute Wilson score continuity-free confidence interval for a binomial proportion.

    Parameters:
        k: Number of successes / positive outcomes.
        n: Total sample size.
        confidence_z: Two-tailed z-score (1.959964 for 95% confidence).

    Returns:
        (lower_bound, upper_bound) rounded to 4 decimal places, or (None, None) if n <= 0.
    """
    if n <= 0:
        return None, None
    p = k / n
    z2 = confidence_z**2
    denom = 1.0 + z2 / n
    center = (p + z2 / (2.0 * n)) / denom
    margin = (confidence_z * np.sqrt((p * (1.0 - p) / n) + (z2 / (4.0 * (n**2))))) / denom
    lower = max(0.0, round(float(center - margin), 4))
    upper = min(1.0, round(float(center + margin), 4))
    return lower, upper


class CustomerOutcomeRecord(BaseModel):
    """Individual customer outcome evaluation record for a single historical cutoff."""

    customer_id: int
    customer_code: str
    customer_segment: str | None = None
    eligible_historical_orders: int
    baseline_cadence_days: float | None = None
    days_since_last_purchase: float | None = None
    cadence_ratio: float | None = None
    risk_tier: CadenceRiskTier
    cadence_source: str
    future_orders_in_horizon: int
    observed_repeat_purchase: bool
    outcome_no_purchase: bool | None = None
    is_censored: bool = False
    is_repeat_buyer: bool = False
    is_followup_verified: bool = False
    unverified_negative_outcome: bool = False


class RiskTierPerformance(BaseModel):
    """Empirical performance metrics within a specific cadence risk tier."""

    risk_tier: CadenceRiskTier
    customer_count: int = Field(description="Total customers assigned to this risk tier.")
    no_purchase_count: int = Field(
        description="Customers in this tier with 0 purchases during the outcome horizon."
    )
    repeat_purchase_count: int = Field(
        description="Customers in this tier who placed >= 1 purchase during the outcome horizon."
    )
    no_purchase_rate: float | None = Field(
        default=None,
        description="Proportion of customers in this tier with no observed repeat purchase.",
    )
    rate_ci_lower: float | None = Field(
        default=None,
        description="95% Wilson score confidence interval lower bound for no-purchase rate.",
    )
    rate_ci_upper: float | None = Field(
        default=None,
        description="95% Wilson score confidence interval upper bound for no-purchase rate.",
    )
    lift_vs_baseline: float | None = Field(
        default=None,
        description="Ratio of tier no-purchase rate to overall cohort baseline rate.",
    )


class ConfusionMatrix(BaseModel):
    """Confusion matrix and classification performance metrics at a specified tier threshold."""

    threshold_description: str = Field(description="Definition of positive prediction threshold.")
    tp: int = Field(description="True Positives: predicted inactive and observed no purchase.")
    fp: int = Field(description="False Positives: predicted inactive but placed repeat purchase.")
    fn: int = Field(description="False Negatives: predicted active but observed no purchase.")
    tn: int = Field(description="True Negatives: predicted active and placed repeat purchase.")
    precision: float | None = Field(default=None, description="TP / (TP + FP)")
    recall: float | None = Field(default=None, description="TP / (TP + FN)")
    f1_score: float | None = Field(default=None, description="Harmonic mean of precision & recall.")
    accuracy: float | None = Field(default=None, description="(TP + TN) / Total")
    specificity: float | None = Field(default=None, description="TN / (TN + FP)")


class CutoffEvaluationResult(BaseModel):
    """Comprehensive evaluation metrics for a single historical cutoff date."""

    cutoff_date: str = Field(description="Historical evaluation cutoff timestamp (UTC ISO-8601).")
    buffer_days: int = Field(description="Ingestion lag buffer days immediately following cutoff.")
    horizon_days: int = Field(description="Forward outcome evaluation window in days.")
    outcome_window_start: str = Field(description="UTC timestamp of outcome window start.")
    outcome_window_end: str = Field(description="UTC timestamp of outcome window end.")
    is_complete_followup: bool = Field(
        description="Whether the full outcome horizon has elapsed in available data."
    )
    is_followup_verified: bool = Field(
        default=False,
        description="Whether outcome window completeness is corroborated by an authoritative watermark.",
    )
    followup_status: str = Field(
        default="unverified_complete",
        description="Completeness status: 'verified_complete', 'unverified_complete', 'incomplete_censored', or 'incomplete_in_flight'.",
    )
    censoring_reason: str | None = Field(
        default=None, description="Explanation if future follow-up is right-censored."
    )
    total_customers_evaluated: int
    scored_customers_count: int
    insufficient_history_count: int
    repeat_buyers_count: int = 0
    one_time_buyers_count: int = 0
    baseline_no_purchase_rate: float | None = Field(
        default=None,
        description="Proportion of all scored cohort customers who had no repeat purchase.",
    )
    baseline_ci_lower: float | None = None
    baseline_ci_upper: float | None = None
    tier_performances: dict[str, RiskTierPerformance]
    confusion_matrices: dict[str, ConfusionMatrix]
    critical_precision: float | None = None
    critical_lift: float | None = None
    high_critical_recall: float | None = None
    high_critical_precision: float | None = None
    high_critical_lift: float | None = None
    customer_records: list[CustomerOutcomeRecord] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class HistoricalValidationSummary(BaseModel):
    """Aggregate multi-cutoff historical validation summary."""

    business_id: str | None = None
    cutoffs_evaluated: int
    complete_cutoffs_count: int
    incomplete_cutoffs_count: int
    verified_cutoffs_count: int = Field(
        default=0,
        description="Count of cutoffs with verified complete follow-up against an authoritative watermark.",
    )
    unverified_cutoffs_count: int = Field(
        default=0,
        description="Count of cutoffs with unverified completeness (relying solely on observed transaction dates).",
    )
    total_scored_observations: int
    pooled_critical_precision: float | None = None
    pooled_high_critical_recall: float | None = None
    pooled_critical_lift: float | None = None
    cutoff_results: list[CutoffEvaluationResult]
    methodology: str = Field(
        default=(
            "Historical temporal backtesting comparing heuristic cadence risk tiers evaluated "
            "at cutoff T against empirical repeat-purchase events in [T + buffer, T + buffer + horizon]."
        )
    )
    overlapping_cohort_notice: str = Field(
        default=(
            "When historical cutoffs are separated by less than (lookback + horizon), customer "
            "cohort memberships overlap across adjacent cutoffs, inducing statistical dependence."
        )
    )
    limitations: list[str] = Field(default_factory=list)


class HistoricalCadenceValidator:
    """Orchestrates historical validation and backtesting of purchase cadence heuristics."""

    @classmethod
    def evaluate_cutoff(
        cls,
        session: Session,
        context: AnalysisContext | None = None,
        cutoff_date: datetime | date | None = None,
        buffer_days: int = 7,
        horizon_days: int = 60,
        cadence_config: CadenceConfig | None = None,
        eligible_statuses: list[str] | None = None,
        include_customer_records: bool = True,
        ingestion_watermark: datetime | date | Any | None = None,
        require_verified_watermark: bool = False,
    ) -> CutoffEvaluationResult:
        """
        Evaluate customer cadence risk at a historical cutoff and measure subsequent reordering.

        Parameters:
            session: Active SQLAlchemy database session.
            context: Standard AnalysisContext specifying tenant boundary.
            cutoff_date: Historical evaluation cutoff timestamp.
            buffer_days: Gap between cutoff and outcome horizon (simulates ingestion latency).
            horizon_days: Duration of the forward outcome evaluation window.
            cadence_config: Operational cadence thresholds.
            eligible_statuses: Valid purchase statuses for both features and labels.
            include_customer_records: Whether to attach individual customer rows.
            ingestion_watermark: Optional authoritative pipeline watermark or reporting-period close.
        """
        if buffer_days < 0:
            raise ValueError(f"buffer_days cannot be negative, got {buffer_days}")
        if horizon_days <= 0:
            raise ValueError(f"horizon_days must be strictly positive, got {horizon_days}")

        cfg = cadence_config or CadenceConfig()
        statuses = eligible_statuses or (
            context.statuses if (context and context.statuses) else cfg.eligible_statuses
        )

        # 1. Normalize cutoff timestamp (UTC)
        if cutoff_date is not None:
            if isinstance(cutoff_date, datetime):
                ref_dt = (
                    cutoff_date
                    if cutoff_date.tzinfo is not None
                    else cutoff_date.replace(tzinfo=UTC)
                )
                ref_dt = ref_dt.astimezone(UTC)
            elif isinstance(cutoff_date, date):
                ref_dt = datetime.combine(
                    cutoff_date, datetime.max.time().replace(microsecond=0), tzinfo=UTC
                )
            else:
                raise ValueError(f"Invalid cutoff_date type: {type(cutoff_date)}")
        elif context and context.date_to is not None:
            ref_dt = (
                context.date_to
                if context.date_to.tzinfo is not None
                else context.date_to.replace(tzinfo=UTC)
            )
            ref_dt = ref_dt.astimezone(UTC)
        else:
            raise ValueError("cutoff_date must be explicitly specified for historical validation.")

        # 2. Define forward outcome window
        outcome_start = ref_dt + timedelta(days=buffer_days)
        outcome_end = outcome_start + timedelta(days=horizon_days)

        # 3. Check for right-censoring and outcome follow-up completeness
        # Check for in-flight or failed ingestion jobs for tenant
        in_flight_job = None
        if context and context.business_id:
            in_flight_job = session.execute(
                select(IngestionJob.id)
                .where(
                    IngestionJob.business_id == context.business_id,
                    IngestionJob.status.in_(["PENDING", "PROCESSING", "FAILED", "REQUIRES_REVIEW"]),
                )
                .limit(1)
            ).scalar_one_or_none()

        effective_wm = None
        if context and context.business_id and ingestion_watermark is None:
            try:
                from app.services.watermark_service import WatermarkService
                effective_wm = WatermarkService.get_effective_tenant_watermark(session, context.business_id)
            except Exception:  # noqa: BLE001
                effective_wm = None

        max_dt_stmt = select(func.max(Sale.transaction_date))
        if context and context.business_id:
            max_dt_stmt = max_dt_stmt.where(Sale.business_id == context.business_id)
        db_max_dt = session.execute(max_dt_stmt).scalar()

        if in_flight_job is not None:
            is_complete = False
            is_verified = False
            followup_status = "incomplete_in_flight"
            censoring_reason = (
                "Unresolved or in-flight data ingestion job detected for tenant; "
                "follow-up transactions are incomplete."
            )
        elif effective_wm and effective_wm.status == "incomplete_in_flight":
            is_complete = False
            is_verified = False
            followup_status = "incomplete_in_flight"
            censoring_reason = "; ".join(effective_wm.blocking_reasons)
        elif effective_wm and effective_wm.status == "invalidated":
            is_complete = False
            is_verified = False
            followup_status = "incomplete_watermark_invalidated"
            censoring_reason = "; ".join(effective_wm.blocking_reasons)
        elif effective_wm and effective_wm.status == "incomplete_watermark_gap":
            is_complete = False
            is_verified = False
            followup_status = "incomplete_watermark_gap"
            censoring_reason = "; ".join(effective_wm.blocking_reasons)
        elif ingestion_watermark is not None or (effective_wm and effective_wm.is_verified):
            wm_obj = ingestion_watermark if ingestion_watermark is not None else effective_wm.effective_complete_through_dt
            if hasattr(wm_obj, "complete_through_dt"):
                watermark_dt = wm_obj.complete_through_dt
            elif hasattr(wm_obj, "effective_complete_through_dt"):
                watermark_dt = wm_obj.effective_complete_through_dt
            elif isinstance(wm_obj, datetime):
                watermark_dt = (
                    wm_obj
                    if wm_obj.tzinfo is not None
                    else wm_obj.replace(tzinfo=UTC)
                )
                watermark_dt = watermark_dt.astimezone(UTC)
            elif isinstance(wm_obj, date):
                watermark_dt = datetime.combine(
                    wm_obj, datetime.max.time().replace(microsecond=0), tzinfo=UTC
                )
            else:
                raise ValueError(f"Invalid ingestion_watermark type: {type(wm_obj)}")

            if watermark_dt < outcome_end:
                is_complete = False
                is_verified = True
                followup_status = "incomplete_censored"
                censoring_reason = (
                    f"Authoritative ingestion watermark ({watermark_dt.isoformat()}) precedes "
                    f"outcome window end ({outcome_end.isoformat()}). Outcome follow-up was right-censored."
                )
            else:
                is_complete = True
                is_verified = True
                followup_status = "verified_complete"
                censoring_reason = None
        elif db_max_dt is not None:
            db_max_utc = (
                db_max_dt if db_max_dt.tzinfo is not None else db_max_dt.replace(tzinfo=UTC)
            )
            db_max_utc = db_max_utc.astimezone(UTC)
            if db_max_utc < outcome_end:
                is_complete = False
                is_verified = False
                followup_status = "incomplete_censored"
                censoring_reason = (
                    f"Latest transaction in database ({db_max_utc.isoformat()}) precedes "
                    f"outcome window end ({outcome_end.isoformat()}). Outcome follow-up was right-censored due to incomplete data."
                )
            elif require_verified_watermark:
                is_complete = False
                is_verified = False
                followup_status = "incomplete_censored"
                censoring_reason = (
                    "Follow-up was right-censored because require_verified_watermark=True "
                    "and no verified authoritative watermark exists."
                )
            else:
                is_complete = True
                is_verified = False
                followup_status = "unverified_complete"
                censoring_reason = None
        else:
            is_complete = False
            is_verified = False
            followup_status = "incomplete_censored"
            censoring_reason = "No transactions found in database."

        # 4. Evaluate cadence baseline strictly at or before cutoff (Zero Future Leakage)
        cadence_summary: CustomerCadenceSummary = CustomerCadenceAnalyzer.evaluate(
            session=session,
            context=context,
            as_of_date=ref_dt,
            config=cfg,
        )

        total_customers = cadence_summary.total_customers_evaluated
        scored_customers = cadence_summary.customers_scored
        insufficient_customers = cadence_summary.insufficient_history_count

        if total_customers == 0:
            return CutoffEvaluationResult(
                cutoff_date=ref_dt.isoformat(),
                buffer_days=buffer_days,
                horizon_days=horizon_days,
                outcome_window_start=outcome_start.isoformat(),
                outcome_window_end=outcome_end.isoformat(),
                is_complete_followup=is_complete,
                is_followup_verified=is_verified,
                followup_status=followup_status,
                censoring_reason=censoring_reason,
                total_customers_evaluated=0,
                scored_customers_count=0,
                insufficient_history_count=0,
                baseline_no_purchase_rate=None,
                tier_performances={},
                confusion_matrices={},
                limitations=["No eligible customers found at cutoff date."],
            )

        # 5. Query future eligible orders strictly inside the outcome horizon
        cust_ids = [r.customer_id for r in cadence_summary.records]
        outcome_sales_stmt = (
            select(
                Sale.customer_id,
                func.count(Sale.id).label("order_count"),
            )
            .join(Customer, Customer.id == Sale.customer_id)
            .where(
                Sale.status.in_(statuses),
                Sale.transaction_date >= outcome_start,
                Sale.transaction_date <= outcome_end,
                Customer.id.in_(cust_ids),
            )
            .group_by(Sale.customer_id)
        )
        if context and context.business_id:
            outcome_sales_stmt = outcome_sales_stmt.where(
                Sale.business_id == context.business_id,
                Customer.business_id == context.business_id,
            )

        outcome_rows = session.execute(outcome_sales_stmt).all()
        future_orders_map = {row.customer_id: row.order_count for row in outcome_rows}

        # 6. Build individual customer outcome records
        outcome_records: list[CustomerOutcomeRecord] = []
        for r in cadence_summary.records:
            f_orders = future_orders_map.get(r.customer_id, 0)
            has_repeat = f_orders > 0
            rec_unverified_neg = False
            if is_complete:
                rec_no_purchase = not has_repeat
                rec_censored = False
                if not is_verified and rec_no_purchase:
                    rec_unverified_neg = True
            else:
                if has_repeat:
                    rec_no_purchase = False
                    rec_censored = False
                else:
                    # Incomplete follow-up: zero observed orders is right-censored, NOT confirmed no purchase
                    rec_no_purchase = None
                    rec_censored = True

            rec = CustomerOutcomeRecord(
                customer_id=r.customer_id,
                customer_code=r.customer_code,
                customer_segment=r.customer_segment,
                eligible_historical_orders=r.eligible_order_count,
                baseline_cadence_days=r.baseline_cadence_days,
                days_since_last_purchase=r.days_since_last_purchase,
                cadence_ratio=r.cadence_ratio,
                risk_tier=r.risk_tier,
                cadence_source=r.cadence_source,
                future_orders_in_horizon=f_orders,
                observed_repeat_purchase=has_repeat,
                outcome_no_purchase=rec_no_purchase,
                is_censored=rec_censored,
                is_repeat_buyer=getattr(r, "is_repeat_buyer", r.eligible_order_count >= 2),
                is_followup_verified=is_verified,
                unverified_negative_outcome=rec_unverified_neg,
            )
            outcome_records.append(rec)

        # 7. Calculate cohort baseline and tier-level performance metrics
        scored_records = [
            r for r in outcome_records if r.risk_tier != CadenceRiskTier.INSUFFICIENT_HISTORY
        ]
        n_scored = len(scored_records)

        tier_performances: dict[str, RiskTierPerformance] = {}
        confusion_matrices: dict[str, ConfusionMatrix] = {}

        if not is_complete:
            # Right-censored follow-up: complete horizon outcomes are unobservable for non-repurchasers
            baseline_rate = None
            b_lower, b_upper = None, None
            for tier in CadenceRiskTier:
                t_records = [r for r in outcome_records if r.risk_tier == tier]
                t_count = len(t_records)
                t_repeat = sum(1 for r in t_records if r.observed_repeat_purchase)
                tier_performances[tier.value] = RiskTierPerformance(
                    risk_tier=tier,
                    customer_count=t_count,
                    no_purchase_count=0,
                    repeat_purchase_count=t_repeat,
                    no_purchase_rate=None,
                    rate_ci_lower=None,
                    rate_ci_upper=None,
                    lift_vs_baseline=None,
                )
            crit_prec = None
            crit_lift = None
            high_crit_rec = None
            high_crit_prec = None
            high_crit_lift = None
        else:
            n_pos_scored = sum(1 for r in scored_records if r.outcome_no_purchase is True)

            if n_scored > 0:
                baseline_rate = round(n_pos_scored / n_scored, 4)
                b_lower, b_upper = compute_wilson_score_interval(n_pos_scored, n_scored)
            else:
                baseline_rate = None
                b_lower, b_upper = None, None

            for tier in CadenceRiskTier:
                t_records = [r for r in outcome_records if r.risk_tier == tier]
                t_count = len(t_records)
                t_no_purch = sum(1 for r in t_records if r.outcome_no_purchase is True)
                t_repeat = t_count - t_no_purch

                if tier == CadenceRiskTier.INSUFFICIENT_HISTORY:
                    t_rate = round(t_no_purch / t_count, 4) if t_count > 0 else None
                    ci_l, ci_u = compute_wilson_score_interval(t_no_purch, t_count) if t_count > 0 else (None, None)
                    lift = None  # Insufficient history is an unscored cohort; lift against scored baseline is undefined
                elif t_count > 0:
                    t_rate = round(t_no_purch / t_count, 4)
                    ci_l, ci_u = compute_wilson_score_interval(t_no_purch, t_count)
                    lift = (
                        round(t_rate / baseline_rate, 4)
                        if (baseline_rate is not None and baseline_rate > 0)
                        else None
                    )
                else:
                    t_rate = None
                    ci_l, ci_u = None, None
                    lift = None

                tier_performances[tier.value] = RiskTierPerformance(
                    risk_tier=tier,
                    customer_count=t_count,
                    no_purchase_count=t_no_purch,
                    repeat_purchase_count=t_repeat,
                    no_purchase_rate=t_rate,
                    rate_ci_lower=ci_l,
                    rate_ci_upper=ci_u,
                    lift_vs_baseline=lift,
                )

            # 8. Confusion matrices at tier thresholds
            if n_scored > 0:
                # Threshold: >= Critical
                confusion_matrices["critical"] = cls._build_confusion_matrix(
                    scored_records=scored_records,
                    predicted_positive_tiers={CadenceRiskTier.CRITICAL},
                    threshold_description="Risk Tier = CRITICAL (cadence ratio >= 3.0x)",
                )
                # Threshold: >= High (High + Critical)
                confusion_matrices["high_critical"] = cls._build_confusion_matrix(
                    scored_records=scored_records,
                    predicted_positive_tiers={CadenceRiskTier.HIGH, CadenceRiskTier.CRITICAL},
                    threshold_description="Risk Tier >= HIGH (cadence ratio >= 2.0x)",
                )

            crit_cm = confusion_matrices.get("critical")
            high_crit_cm = confusion_matrices.get("high_critical")

            crit_perf = tier_performances.get("critical")
            high_perf = tier_performances.get("high")

            crit_prec = crit_cm.precision if crit_cm else None
            crit_lift = crit_perf.lift_vs_baseline if crit_perf else None

            high_crit_rec = high_crit_cm.recall if high_crit_cm else None
            high_crit_prec = high_crit_cm.precision if high_crit_cm else None

            # Calculate combined High + Critical lift
            if (
                high_perf
                and crit_perf
                and (high_perf.customer_count + crit_perf.customer_count) > 0
                and baseline_rate
                and baseline_rate > 0
            ):
                combined_pos = high_perf.no_purchase_count + crit_perf.no_purchase_count
                combined_n = high_perf.customer_count + crit_perf.customer_count
                high_crit_lift = round((combined_pos / combined_n) / baseline_rate, 4)
            else:
                high_crit_lift = None

        limitations = [
            "Target outcome represents 'no observed repeat purchase during evaluation horizon', not permanent churn.",
            "Non-contractual transactions are subject to right-censoring; long-cadence buyers may repurchase after horizon.",
            "Performance is evaluated on heuristic cadence ratios, not calibrated probabilities.",
        ]
        if not is_complete:
            limitations.append(
                censoring_reason or "Outcome follow-up was right-censored due to incomplete data."
            )
        elif not is_verified:
            limitations.append(
                "Follow-up completeness is unverified: MAX(Sale.transaction_date) reaches outcome window end, "
                "but no authoritative ingestion watermark or reporting-period close was provided. "
                "Late-arriving or un-ingested transactions cannot be ruled out."
            )
            limitations.append(
                "UNVERIFIED OUTCOMES NOTICE: Observed non-purchases in unverified follow-up windows must NOT "
                "be silently treated as definitive customer churn or used for uncalibrated commercial action."
            )

        return CutoffEvaluationResult(
            cutoff_date=ref_dt.isoformat(),
            buffer_days=buffer_days,
            horizon_days=horizon_days,
            outcome_window_start=outcome_start.isoformat(),
            outcome_window_end=outcome_end.isoformat(),
            is_complete_followup=is_complete,
            is_followup_verified=is_verified,
            followup_status=followup_status,
            censoring_reason=censoring_reason,
            total_customers_evaluated=total_customers,
            scored_customers_count=scored_customers,
            insufficient_history_count=insufficient_customers,
            repeat_buyers_count=cadence_summary.repeat_buyers_count,
            one_time_buyers_count=cadence_summary.one_time_buyers_count,
            baseline_no_purchase_rate=baseline_rate,
            baseline_ci_lower=b_lower,
            baseline_ci_upper=b_upper,
            tier_performances=tier_performances,
            confusion_matrices=confusion_matrices,
            critical_precision=crit_prec,
            critical_lift=crit_lift,
            high_critical_recall=high_crit_rec,
            high_critical_precision=high_crit_prec,
            high_critical_lift=high_crit_lift,
            customer_records=outcome_records if include_customer_records else [],
            limitations=limitations,
        )

    @classmethod
    def evaluate_multi_cutoff(
        cls,
        session: Session,
        context: AnalysisContext | None = None,
        cutoff_dates: list[datetime | date] | None = None,
        buffer_days: int = 7,
        horizon_days: int = 60,
        cadence_config: CadenceConfig | None = None,
        eligible_statuses: list[str] | None = None,
        ingestion_watermarks: list[datetime | date | None] | None = None,
    ) -> HistoricalValidationSummary:
        """
        Execute multi-cutoff temporal validation over a sequence of historical dates.

        Parameters:
            session: Active SQLAlchemy database session.
            context: Standard AnalysisContext specifying tenant boundary.
            cutoff_dates: Chronological list of historical cutoffs.
            buffer_days: Ingestion lag buffer days.
            horizon_days: Forward outcome evaluation window.
            cadence_config: Cadence thresholds configuration.
            eligible_statuses: Valid purchase statuses.
            ingestion_watermarks: Optional sequence of watermarks corresponding to each cutoff date.
        """
        if not cutoff_dates:
            raise ValueError("cutoff_dates list must contain at least one evaluation cutoff date.")

        results: list[CutoffEvaluationResult] = []
        for idx, dt in enumerate(cutoff_dates):
            wm = (
                ingestion_watermarks[idx]
                if (ingestion_watermarks and idx < len(ingestion_watermarks))
                else None
            )
            res = cls.evaluate_cutoff(
                session=session,
                context=context,
                cutoff_date=dt,
                buffer_days=buffer_days,
                horizon_days=horizon_days,
                cadence_config=cadence_config,
                eligible_statuses=eligible_statuses,
                include_customer_records=False,
                ingestion_watermark=wm,
            )
            results.append(res)

        complete_results = [r for r in results if r.is_complete_followup]
        verified_count = sum(1 for r in complete_results if r.is_followup_verified)
        unverified_count = sum(1 for r in complete_results if not r.is_followup_verified)

        # Calculate pooled micro-average metrics across all completed cutoffs
        total_scored = sum(r.scored_customers_count for r in complete_results)

        pooled_crit_tp = sum(
            r.confusion_matrices["critical"].tp
            for r in complete_results
            if "critical" in r.confusion_matrices
        )
        pooled_crit_fp = sum(
            r.confusion_matrices["critical"].fp
            for r in complete_results
            if "critical" in r.confusion_matrices
        )
        pooled_crit_n = pooled_crit_tp + pooled_crit_fp
        pooled_crit_prec = round(pooled_crit_tp / pooled_crit_n, 4) if pooled_crit_n > 0 else None

        pooled_high_crit_tp = sum(
            r.confusion_matrices["high_critical"].tp
            for r in complete_results
            if "high_critical" in r.confusion_matrices
        )
        pooled_high_crit_fn = sum(
            r.confusion_matrices["high_critical"].fn
            for r in complete_results
            if "high_critical" in r.confusion_matrices
        )
        pooled_pos = pooled_high_crit_tp + pooled_high_crit_fn
        pooled_high_crit_rec = (
            round(pooled_high_crit_tp / pooled_pos, 4) if pooled_pos > 0 else None
        )

        pooled_base_rate = (
            round(pooled_pos / total_scored, 4) if (total_scored > 0 and pooled_pos > 0) else None
        )
        pooled_crit_lift = (
            round(pooled_crit_prec / pooled_base_rate, 4)
            if (pooled_crit_prec is not None and pooled_base_rate and pooled_base_rate > 0)
            else None
        )

        limitations = [
            "Micro-averaged aggregate metrics pool observations across cutoffs; adjacent cutoffs may share customers.",
            "Heuristic risk tiers are deterministic indicators, not calibrated churn probabilities.",
        ]
        if len(results) > len(complete_results):
            limitations.append(
                f"{len(results) - len(complete_results)} cutoffs were right-censored due to incomplete outcome windows and excluded from pooled performance metrics."
            )
        if unverified_count > 0:
            limitations.append(
                f"{unverified_count} cutoffs have unverified follow-up completeness (relying solely on observed transaction dates without an authoritative ingestion watermark)."
            )

        return HistoricalValidationSummary(
            business_id=context.business_id if context else None,
            cutoffs_evaluated=len(results),
            complete_cutoffs_count=len(complete_results),
            incomplete_cutoffs_count=len(results) - len(complete_results),
            verified_cutoffs_count=verified_count,
            unverified_cutoffs_count=unverified_count,
            total_scored_observations=total_scored,
            pooled_critical_precision=pooled_crit_prec,
            pooled_high_critical_recall=pooled_high_crit_rec,
            pooled_critical_lift=pooled_crit_lift,
            cutoff_results=results,
            limitations=limitations,
        )

    @staticmethod
    def _build_confusion_matrix(
        scored_records: list[CustomerOutcomeRecord],
        predicted_positive_tiers: set[CadenceRiskTier],
        threshold_description: str,
    ) -> ConfusionMatrix:
        """Construct confusion matrix and classification metrics for a specific tier threshold."""
        tp = sum(
            1
            for r in scored_records
            if r.risk_tier in predicted_positive_tiers and r.outcome_no_purchase
        )
        fp = sum(
            1
            for r in scored_records
            if r.risk_tier in predicted_positive_tiers and not r.outcome_no_purchase
        )
        fn = sum(
            1
            for r in scored_records
            if r.risk_tier not in predicted_positive_tiers and r.outcome_no_purchase
        )
        tn = sum(
            1
            for r in scored_records
            if r.risk_tier not in predicted_positive_tiers and not r.outcome_no_purchase
        )

        precision = round(tp / (tp + fp), 4) if (tp + fp) > 0 else None
        recall = round(tp / (tp + fn), 4) if (tp + fn) > 0 else None
        f1 = (
            round(2.0 * precision * recall / (precision + recall), 4)
            if (precision is not None and recall is not None and (precision + recall) > 0)
            else None
        )
        total = tp + fp + fn + tn
        accuracy = round((tp + tn) / total, 4) if total > 0 else None
        specificity = round(tn / (tn + fp), 4) if (tn + fp) > 0 else None

        return ConfusionMatrix(
            threshold_description=threshold_description,
            tp=tp,
            fp=fp,
            fn=fn,
            tn=tn,
            precision=precision,
            recall=recall,
            f1_score=f1,
            accuracy=accuracy,
            specificity=specificity,
        )
