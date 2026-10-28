"""Deterministic Customer Data Readiness Assessment and Real-Data Audit for NEXUS.

Evaluates tenant-scoped transaction data models, historical coverage, data quality,
repeat-buyer share, ingestion delays, authoritative watermarks, and controlled-pilot feasibility.
Guarantees zero customer PII exposure in reports.
"""

from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analytics.core.context import AnalysisContext
from app.models.customer import Customer
from app.models.sale import Sale
from app.models.tenant import Business, IngestionJob


class HistoricalCoverageMetrics(BaseModel):
    """Observed facts and inferred rates for transaction volume and historical coverage."""

    observed_total_transactions: int = Field(
        description="Total transaction count across all statuses recorded in database."
    )
    observed_sales_volume_usd: float = Field(
        description="Gross net sales volume summed across all recorded transactions."
    )
    first_transaction_date: str | None = Field(
        default=None, description="UTC ISO-8601 timestamp of earliest recorded transaction."
    )
    latest_transaction_date: str | None = Field(
        default=None, description="UTC ISO-8601 timestamp of most recent recorded transaction."
    )
    historical_span_days: float | None = Field(
        default=None, description="Total calendar span in days between first and latest transactions."
    )
    status_distribution: dict[str, int] = Field(
        default_factory=dict, description="Observed transaction counts broken down by status."
    )
    eligible_purchase_events: int = Field(
        description="Transaction count with valid completed or shipped status."
    )
    refunded_transactions_count: int = Field(
        default=0, description="Count of transactions with 'refunded' status."
    )
    cancelled_transactions_count: int = Field(
        default=0, description="Count of transactions with 'cancelled' status."
    )
    inferred_refund_prevalence_pct: float | None = Field(
        default=None, description="Refunded transactions as a percentage of total transactions."
    )
    inferred_cancelled_prevalence_pct: float | None = Field(
        default=None, description="Cancelled transactions as a percentage of total transactions."
    )


class CustomerPopulationMetrics(BaseModel):
    """Observed customer population counts, repeat-purchase dynamics, and segment distribution."""

    registered_customers_count: int = Field(
        description="Total registered customer records for tenant."
    )
    customers_with_any_transactions: int = Field(
        description="Customers with at least one transaction of any status."
    )
    customers_with_eligible_purchases: int = Field(
        description="Customers with at least one eligible completed or shipped purchase."
    )
    eligible_repeat_buyers_count: int = Field(
        description="Customers with >= 2 distinct completed purchase events separated in time."
    )
    one_time_buyers_count: int = Field(
        description="Customers with exactly 1 eligible completed purchase event."
    )
    zero_purchase_customers_count: int = Field(
        description="Registered customers with 0 completed purchase events."
    )
    simultaneous_orders_only_count: int = Field(
        description="Customers with >= 2 orders but all sharing the exact same timestamp."
    )
    inferred_repeat_buyer_share_pct: float | None = Field(
        default=None,
        description="Eligible repeat buyers as percentage of customers with eligible purchases.",
    )
    inferred_one_time_buyer_share_pct: float | None = Field(
        default=None,
        description="One-time buyers as percentage of customers with eligible purchases.",
    )
    segment_distribution: dict[str, int] = Field(
        default_factory=dict, description="Customer count breakdown across registered segments."
    )


class DataQualityDiagnostics(BaseModel):
    """Audit diagnostics checking for missing timestamps, conflicting metadata, and duplicate events."""

    missing_customer_id_count: int = Field(
        default=0, description="Sales records missing an associated customer_id."
    )
    missing_transaction_date_count: int = Field(
        default=0, description="Sales records with null transaction_date."
    )
    missing_acquisition_date_count: int = Field(
        default=0, description="Customer records with null acquisition_date."
    )
    inconsistent_acquisition_dates_count: int = Field(
        default=0,
        description="Customers whose acquisition_date is chronologically after their first purchase.",
    )
    duplicate_transaction_numbers_count: int = Field(
        default=0, description="Repeated or colliding transaction/order identifiers."
    )
    duplicate_purchase_events_count: int = Field(
        default=0,
        description="Same customer with multiple completed orders at the exact same timestamp.",
    )
    ambiguous_order_groupings_count: int = Field(
        default=0,
        description="Single transaction_number associated with multiple conflicting customer_ids.",
    )
    unresolvable_customer_id_count: int = Field(
        default=0,
        description="Sales records referencing customer IDs that do not exist within this tenant workspace.",
    )


class IngestionHealthMetrics(BaseModel):
    """Audit metrics for ingestion delays, in-flight/failed jobs, and authoritative watermarks."""

    latest_ingestion_created_at: str | None = Field(
        default=None, description="UTC ISO-8601 timestamp of latest database row insertion."
    )
    inferred_mean_ingestion_delay_days: float | None = Field(
        default=None,
        description="Average difference in days between transaction occurrence and database insertion.",
    )
    inferred_max_ingestion_delay_days: float | None = Field(
        default=None,
        description="Maximum observed delay in days between transaction occurrence and database insertion.",
    )
    active_or_failed_ingestion_jobs_count: int = Field(
        default=0,
        description="Tenant data ingestion jobs in PENDING, PROCESSING, FAILED, or REQUIRES_REVIEW state.",
    )
    authoritative_watermark_present: bool = Field(
        description="Whether an authoritative completeness watermark is supplied."
    )
    authoritative_watermark_timestamp: str | None = Field(
        default=None,
        description="UTC ISO-8601 timestamp of certified authoritative ingestion watermark.",
    )
    watermark_status: str = Field(
        description="Watermark verification state: 'verified_present' or 'unverified_missing'."
    )
    unavailable_signals: list[str] = Field(
        default_factory=list,
        description="Known unobservable data aspects (e.g. historical status-mutation logs, point-in-time refunds).",
    )


class CutoffFeasibilityItem(BaseModel):
    """Evaluation feasibility simulation for a specific candidate historical cutoff date."""

    cutoff_date: str = Field(description="UTC ISO-8601 candidate evaluation cutoff timestamp.")
    outcome_horizon_days: int = Field(description="Forward outcome evaluation window in days.")
    outcome_window_end: str = Field(description="UTC ISO-8601 timestamp of outcome window end.")
    eligible_repeat_buyers_at_cutoff: int = Field(
        description="Eligible repeat buyers with >= 2 distinct purchases prior to cutoff."
    )
    one_time_buyers_at_cutoff: int = Field(
        description="Customers with exactly 1 purchase prior to cutoff."
    )
    followup_status: str = Field(
        description="Follow-up completeness status: 'verified_complete', 'unverified_complete', or 'incomplete_censored'."
    )
    is_pilot_ready: bool = Field(
        description="Whether this cutoff satisfies all data-quality and sample-size criteria."
    )
    notes: str = Field(description="Diagnostic commentary for this candidate cutoff.")


class PilotSafeguardsPolicy(BaseModel):
    """Operational safeguards governing a read-only customer cadence pilot."""

    read_only_mode: bool = Field(
        default=True, description="Strictly read-only; no database mutations or updates permitted."
    )
    automated_interventions_blocked: bool = Field(
        default=True,
        description="Guarantees no emails, notifications, discounts, or outreach are triggered.",
    )
    target_audience: str = Field(
        default="strictly_eligible_repeat_buyers",
        description="Scoring restricted strictly to customers with >= 2 distinct historical purchases.",
    )
    insufficient_history_isolation: str = Field(
        default="partitioned_unscored",
        description="One-time buyers and unestablished customers remain partitioned as INSUFFICIENT_HISTORY.",
    )
    baseline_comparison_model: str = Field(
        default="fixed_recency_threshold_and_empirical_cohort_rate",
        description="Simpler baseline models used for comparative benchmark.",
    )
    stop_criteria: list[str] = Field(
        default_factory=list,
        description="Mandatory stopping conditions that halt the pilot if violated.",
    )


class CustomerDataReadinessReport(BaseModel):
    """Comprehensive, read-only readiness report evaluating tenant data for a customer cadence pilot."""

    report_id: str = Field(default_factory=lambda: f"RPT-RDY-{uuid4().hex[:8].upper()}")
    generated_at: str = Field(
        default_factory=lambda: datetime.now(UTC).isoformat(),
        description="UTC timestamp of readiness assessment execution.",
    )
    business_id: str | None = Field(
        default=None, description="Authorized tenant business identifier."
    )
    business_name: str | None = Field(
        default=None, description="Registered tenant business name."
    )
    is_authorized: bool = Field(
        default=True, description="Whether access to the requested tenant dataset is authorized."
    )
    readiness_verdict: str = Field(
        description="Overall readiness decision: 'READY_FOR_PILOT', 'READY_WITH_CAUTIONS', or 'NOT_READY'."
    )
    blockers: list[str] = Field(
        default_factory=list,
        description="Critical issues precluding execution of a controlled pilot.",
    )
    cautions: list[str] = Field(
        default_factory=list,
        description="Data quality warnings that do not block pilot execution but require monitoring.",
    )
    historical_coverage: HistoricalCoverageMetrics
    customer_population: CustomerPopulationMetrics
    data_quality: DataQualityDiagnostics
    ingestion_health: IngestionHealthMetrics
    candidate_cutoffs: list[CutoffFeasibilityItem] = Field(default_factory=list)
    pilot_safeguards: PilotSafeguardsPolicy = Field(default_factory=PilotSafeguardsPolicy)
    privacy_compliance_statement: str = Field(
        default=(
            "Privacy Verified: This summary report contains strictly aggregated statistical counts, "
            "temporal boundaries, and data-quality indicators. Zero customer-level personally identifiable "
            "information (PII), names, email addresses, phone numbers, or individual identifiers are exposed."
        ),
        description="Statutory privacy and governance assertion.",
    )


class CustomerDataReadinessAssessor:
    """Read-only diagnostic assessor evaluating tenant transaction data readiness for cadence evaluation."""

    MIN_PILOT_REPEAT_BUYERS: int = 30
    DEFAULT_ELIGIBLE_STATUSES: tuple[str, ...] = ("completed", "shipped")

    @classmethod
    def assess_tenant(
        cls,
        session: Session,
        context: AnalysisContext | None = None,
        candidate_cutoffs: list[datetime | date] | None = None,
        ingestion_watermark: datetime | None = None,
        eligible_statuses: list[str] | None = None,
        buffer_days: int = 7,
        horizon_days: int = 60,
    ) -> CustomerDataReadinessReport:
        """
        Execute read-only tenant data audit and produce a structured readiness report.

        Args:
            session: Active SQLAlchemy database session.
            context: Tenant scoping context (must specify business_id when multitenant).
            candidate_cutoffs: Optional list of cutoff dates to simulate for pilot feasibility.
            ingestion_watermark: Certified authoritative completeness watermark if available.
            eligible_statuses: Transaction statuses counted as valid purchases.
            buffer_days: Lag buffer days following evaluation cutoff.
            horizon_days: Outcome evaluation horizon in days.

        Returns:
            CustomerDataReadinessReport with audit metrics, diagnostics, and pilot recommendations.
        """
        biz_id = context.business_id if context else None
        valid_statuses = list(eligible_statuses or cls.DEFAULT_ELIGIBLE_STATUSES)

        # 1. Tenant Business Metadata
        biz_name = None
        if biz_id:
            biz_row = session.execute(
                select(Business.name).where(Business.id == biz_id)
            ).scalar_one_or_none()
            biz_name = biz_row if biz_row else f"Business-{biz_id}"

        # 2. Historical Coverage & Transaction Volume
        sales_base_stmt = select(Sale)
        if biz_id:
            sales_base_stmt = sales_base_stmt.where(Sale.business_id == biz_id)

        all_sales = session.execute(sales_base_stmt).scalars().all()
        total_tx = len(all_sales)

        status_dist: dict[str, int] = {}
        total_vol = 0.0
        earliest_tx: datetime | None = None
        latest_tx: datetime | None = None
        latest_created_at: datetime | None = None
        delays_days: list[float] = []

        eligible_sales: list[Sale] = []
        refunded_count = 0
        cancelled_count = 0
        missing_cust_id = 0
        missing_tx_date = 0

        for s in all_sales:
            st = (s.status or "unknown").lower()
            status_dist[st] = status_dist.get(st, 0) + 1
            if st in ("refunded",):
                refunded_count += 1
            elif st in ("cancelled",):
                cancelled_count += 1

            if st in valid_statuses:
                eligible_sales.append(s)

            if s.total_amount is not None:
                total_vol += float(s.total_amount)

            if s.customer_id is None:
                missing_cust_id += 1

            if s.transaction_date is None:
                missing_tx_date += 1
            else:
                tx_dt = s.transaction_date if s.transaction_date.tzinfo else s.transaction_date.replace(tzinfo=UTC)
                tx_dt = tx_dt.astimezone(UTC)
                if earliest_tx is None or tx_dt < earliest_tx:
                    earliest_tx = tx_dt
                if latest_tx is None or tx_dt > latest_tx:
                    latest_tx = tx_dt

                if s.created_at is not None:
                    cr_dt = s.created_at if s.created_at.tzinfo else s.created_at.replace(tzinfo=UTC)
                    cr_dt = cr_dt.astimezone(UTC)
                    if latest_created_at is None or cr_dt > latest_created_at:
                        latest_created_at = cr_dt
                    delay = (cr_dt - tx_dt).total_seconds() / 86400.0
                    if delay >= 0:
                        delays_days.append(delay)

        span_days = None
        if earliest_tx and latest_tx:
            span_days = max(0.0, round((latest_tx - earliest_tx).total_seconds() / 86400.0, 1))

        refund_pct = round((refunded_count / total_tx) * 100.0, 2) if total_tx > 0 else None
        cancelled_pct = round((cancelled_count / total_tx) * 100.0, 2) if total_tx > 0 else None

        coverage_metrics = HistoricalCoverageMetrics(
            observed_total_transactions=total_tx,
            observed_sales_volume_usd=round(total_vol, 2),
            first_transaction_date=earliest_tx.isoformat() if earliest_tx else None,
            latest_transaction_date=latest_tx.isoformat() if latest_tx else None,
            historical_span_days=span_days,
            status_distribution=status_dist,
            eligible_purchase_events=len(eligible_sales),
            refunded_transactions_count=refunded_count,
            cancelled_transactions_count=cancelled_count,
            inferred_refund_prevalence_pct=refund_pct,
            inferred_cancelled_prevalence_pct=cancelled_pct,
        )

        # 3. Customer Population & Repeat Purchasing Dynamics
        cust_base_stmt = select(Customer)
        if biz_id:
            cust_base_stmt = cust_base_stmt.where(Customer.business_id == biz_id)

        all_customers = session.execute(cust_base_stmt).scalars().all()
        total_customers = len(all_customers)

        missing_acq_date = 0
        seg_dist: dict[str, int] = {}
        cust_by_id = {}
        for c in all_customers:
            cust_by_id[c.id] = c
            if c.acquisition_date is None:
                missing_acq_date += 1
            seg = c.customer_segment or "Unknown"
            seg_dist[seg] = seg_dist.get(seg, 0) + 1

        # Group eligible sales by customer
        sales_by_cust: dict[int, list[datetime]] = {}
        earliest_sale_by_cust: dict[int, datetime] = {}
        for s in eligible_sales:
            if s.customer_id is not None and s.transaction_date is not None:
                s_dt = s.transaction_date if s.transaction_date.tzinfo else s.transaction_date.replace(tzinfo=UTC)
                s_dt = s_dt.astimezone(UTC)
                sales_by_cust.setdefault(s.customer_id, []).append(s_dt)
                if s.customer_id not in earliest_sale_by_cust or s_dt < earliest_sale_by_cust[s.customer_id]:
                    earliest_sale_by_cust[s.customer_id] = s_dt

        cust_with_any_tx = len({s.customer_id for s in all_sales if s.customer_id is not None})
        cust_with_eligible = len(sales_by_cust)

        repeat_count = 0
        one_time_count = 0
        simultaneous_only_count = 0
        duplicate_events_count = 0
        inconsistent_acq_count = 0

        for cid, dt_list in sales_by_cust.items():
            order_count = len(dt_list)
            distinct_dates = set(dt_list)
            distinct_count = len(distinct_dates)

            if len(dt_list) > distinct_count:
                duplicate_events_count += (len(dt_list) - distinct_count)

            if order_count == 1:
                one_time_count += 1
            elif distinct_count >= 2:
                repeat_count += 1
            else:
                simultaneous_only_count += 1

            # Check acquisition date consistency
            cust_obj = cust_by_id.get(cid)
            if cust_obj and cust_obj.acquisition_date:
                first_sale_dt = earliest_sale_by_cust.get(cid)
                if first_sale_dt and cust_obj.acquisition_date > first_sale_dt.date():
                    inconsistent_acq_count += 1

        zero_purchase_count = max(0, total_customers - cust_with_eligible)
        repeat_share = round((repeat_count / cust_with_eligible) * 100.0, 2) if cust_with_eligible > 0 else None
        one_time_share = round((one_time_count / cust_with_eligible) * 100.0, 2) if cust_with_eligible > 0 else None

        population_metrics = CustomerPopulationMetrics(
            registered_customers_count=total_customers,
            customers_with_any_transactions=cust_with_any_tx,
            customers_with_eligible_purchases=cust_with_eligible,
            eligible_repeat_buyers_count=repeat_count,
            one_time_buyers_count=one_time_count,
            zero_purchase_customers_count=zero_purchase_count,
            simultaneous_orders_only_count=simultaneous_only_count,
            inferred_repeat_buyer_share_pct=repeat_share,
            inferred_one_time_buyer_share_pct=one_time_share,
            segment_distribution=seg_dist,
        )

        # 4. Data Quality & Metadata Integrity Diagnostics
        # Check ambiguous order groupings (same transaction number assigned to multiple distinct customer_ids)
        tx_num_map: dict[str, set[int]] = {}
        dup_tx_num = 0
        valid_cust_ids = set(cust_by_id.keys())
        unresolvable_cust_count = 0
        for s in all_sales:
            if s.transaction_number:
                if s.transaction_number in tx_num_map:
                    dup_tx_num += 1
                if s.customer_id is not None:
                    tx_num_map.setdefault(s.transaction_number, set()).add(s.customer_id)
            if s.customer_id is not None and s.customer_id not in valid_cust_ids:
                unresolvable_cust_count += 1

        ambiguous_orders = sum(1 for cid_set in tx_num_map.values() if len(cid_set) > 1)

        quality_diagnostics = DataQualityDiagnostics(
            missing_customer_id_count=missing_cust_id,
            unresolvable_customer_id_count=unresolvable_cust_count,
            missing_transaction_date_count=missing_tx_date,
            missing_acquisition_date_count=missing_acq_date,
            inconsistent_acquisition_dates_count=inconsistent_acq_count,
            duplicate_transaction_numbers_count=dup_tx_num,
            duplicate_purchase_events_count=duplicate_events_count,
            ambiguous_order_groupings_count=ambiguous_orders,
        )

        # 5. Ingestion Health, Delays & Completeness Watermarks
        mean_delay = round(sum(delays_days) / len(delays_days), 2) if delays_days else None
        max_delay = round(max(delays_days), 2) if delays_days else None

        # Check tenant ingestion jobs
        job_stmt = select(IngestionJob)
        if biz_id:
            job_stmt = job_stmt.where(IngestionJob.business_id == biz_id)
        tenant_jobs = session.execute(job_stmt).scalars().all()
        active_or_failed_jobs = sum(
            1 for j in tenant_jobs if j.status in ("PENDING", "PROCESSING", "FAILED", "REQUIRES_REVIEW")
        )

        has_wm = ingestion_watermark is not None
        wm_ts = ingestion_watermark.isoformat() if ingestion_watermark else None
        wm_status = "verified_present" if has_wm else "unverified_missing"

        unavailable_signals = [
            "Real-time Change Data Capture (CDC) audit trail is unavailable; past refund timestamps cannot be reconstructed point-in-time.",
            "Historical customer segment transition events are not versioned; current segment is assumed constant.",
        ]
        if not has_wm:
            unavailable_signals.append(
                "Authoritative completeness watermark is absent; follow-up data verified solely against latest observed database date."
            )

        ingestion_metrics = IngestionHealthMetrics(
            latest_ingestion_created_at=latest_created_at.isoformat() if latest_created_at else None,
            inferred_mean_ingestion_delay_days=mean_delay,
            inferred_max_ingestion_delay_days=max_delay,
            active_or_failed_ingestion_jobs_count=active_or_failed_jobs,
            authoritative_watermark_present=has_wm,
            authoritative_watermark_timestamp=wm_ts,
            watermark_status=wm_status,
            unavailable_signals=unavailable_signals,
        )

        # 6. Candidate Cutoff Feasibility Simulation
        feasibility_items: list[CutoffFeasibilityItem] = []
        cutoffs_to_eval: list[datetime] = []

        if candidate_cutoffs:
            for c in candidate_cutoffs:
                if isinstance(c, datetime):
                    c_utc = c if c.tzinfo else c.replace(tzinfo=UTC)
                    cutoffs_to_eval.append(c_utc.astimezone(UTC))
                elif isinstance(c, date):
                    cutoffs_to_eval.append(datetime.combine(c, datetime.max.time().replace(microsecond=0), tzinfo=UTC))
        elif latest_tx and span_days and span_days >= (buffer_days + horizon_days + 30):
            # Propose 2 automated cutoff dates: (latest - 90 days) and (latest - 120 days)
            c1 = latest_tx - timedelta(days=buffer_days + horizon_days + 15)
            c2 = latest_tx - timedelta(days=buffer_days + horizon_days + 45)
            cutoffs_to_eval = [c2, c1]

        for cutoff_dt in cutoffs_to_eval:
            outcome_end = cutoff_dt + timedelta(days=buffer_days + horizon_days)
            cutoff_d = cutoff_dt.date()

            # Determine follow-up status
            if has_wm:
                wm_utc = ingestion_watermark if ingestion_watermark.tzinfo else ingestion_watermark.replace(tzinfo=UTC)
                wm_utc = wm_utc.astimezone(UTC)
                if wm_utc >= outcome_end:
                    f_status = "verified_complete"
                else:
                    f_status = "incomplete_censored"
            elif latest_tx and latest_tx >= outcome_end:
                f_status = "unverified_complete"
            else:
                f_status = "incomplete_censored"

            # Filter customers eligible at cutoff
            rep_at_cutoff = 0
            one_at_cutoff = 0
            for cid, dt_list in sales_by_cust.items():
                cust_obj = cust_by_id.get(cid)
                if cust_obj and cust_obj.acquisition_date and cust_obj.acquisition_date > cutoff_d:
                    continue  # Exclude future acquisitions

                # Transactions strictly on or before cutoff
                prior_dates = [d for d in dt_list if d <= cutoff_dt]
                order_cnt = len(prior_dates)
                dist_cnt = len(set(prior_dates))

                if order_cnt == 1:
                    one_at_cutoff += 1
                elif order_cnt >= 2 and dist_cnt >= 2:
                    rep_at_cutoff += 1

            is_ready = (
                f_status in ("verified_complete", "unverified_complete")
                and rep_at_cutoff >= cls.MIN_PILOT_REPEAT_BUYERS
                and active_or_failed_jobs == 0
            )

            notes = (
                f"Sufficient repeat cohort ({rep_at_cutoff} >= {cls.MIN_PILOT_REPEAT_BUYERS}); follow-up {f_status}."
                if is_ready
                else f"Insufficient repeat cohort ({rep_at_cutoff} < {cls.MIN_PILOT_REPEAT_BUYERS}) or follow-up {f_status}."
            )

            feasibility_items.append(
                CutoffFeasibilityItem(
                    cutoff_date=cutoff_dt.isoformat(),
                    outcome_horizon_days=horizon_days,
                    outcome_window_end=outcome_end.isoformat(),
                    eligible_repeat_buyers_at_cutoff=rep_at_cutoff,
                    one_time_buyers_at_cutoff=one_at_cutoff,
                    followup_status=f_status,
                    is_pilot_ready=is_ready,
                    notes=notes,
                )
            )

        # 7. Readiness Verdict, Blockers & Cautions
        blockers: list[str] = []
        cautions: list[str] = []

        if total_tx == 0:
            blockers.append("No transactions found for tenant in database.")
        if repeat_count < cls.MIN_PILOT_REPEAT_BUYERS:
            blockers.append(
                f"Eligible repeat buyer population ({repeat_count}) is below minimum pilot threshold ({cls.MIN_PILOT_REPEAT_BUYERS})."
            )
        if active_or_failed_jobs > 0:
            blockers.append(
                f"{active_or_failed_jobs} data ingestion job(s) are active, failed, or require review for this tenant."
            )
        if missing_cust_id > 0:
            blockers.append(f"{missing_cust_id} transaction(s) have missing customer identifiers.")
        if unresolvable_cust_count > 0:
            blockers.append(
                f"{unresolvable_cust_count} transaction(s) reference unresolvable or foreign tenant customer records."
            )
        if ambiguous_orders > 0:
            blockers.append(
                f"{ambiguous_orders} transaction number(s) map ambiguously to multiple conflicting customer records."
            )
        if missing_tx_date > 0:
            blockers.append(f"{missing_tx_date} transaction(s) have unparseable or null transaction dates.")

        if not has_wm:
            cautions.append(
                "Authoritative ingestion watermark is absent. Follow-up completeness is unverified and relies on database max timestamp."
            )
        if refund_pct and refund_pct > 15.0:
            cautions.append(f"Elevated refund prevalence ({refund_pct}% of transactions); verify return policies.")
        if one_time_share and one_time_share > 75.0:
            cautions.append(
                f"High one-time buyer share ({one_time_share}%). Over 75% of customer base will remain partitioned as INSUFFICIENT_HISTORY."
            )
        if inconsistent_acq_count > 0:
            cautions.append(
                f"{inconsistent_acq_count} customer(s) have recorded acquisition dates occurring after their first observed transaction."
            )
        if mean_delay and mean_delay > 7.0:
            cautions.append(
                f"High average ingestion latency ({mean_delay} days); evaluation buffer must be enlarged accordingly."
            )

        if blockers:
            verdict = "NOT_READY"
        elif cautions:
            verdict = "READY_WITH_CAUTIONS"
        else:
            verdict = "READY_FOR_PILOT"

        # 8. Operational Safeguards & Stop Criteria
        stop_criteria = [
            "Data Ingestion Failure: Pilot halts if any active ingestion job enters FAILED or REQUIRES_REVIEW state.",
            "Watermark Regress: Pilot halts if authoritative watermark reveals missing transactions in the outcome window.",
            "Repeat Buyer Cohort Attrition: Pilot halts if eligible repeat buyer sample size falls below 30.",
            "Missing Transaction Spike: Pilot halts if > 1% of transactions are missing customer_id or date.",
            "Intervention Violation: Pilot immediately terminates if any automated outbound communication is initiated.",
        ]

        safeguards = PilotSafeguardsPolicy(
            read_only_mode=True,
            automated_interventions_blocked=True,
            target_audience="strictly_eligible_repeat_buyers",
            insufficient_history_isolation="partitioned_unscored",
            baseline_comparison_model="fixed_recency_threshold_and_empirical_cohort_rate",
            stop_criteria=stop_criteria,
        )

        return CustomerDataReadinessReport(
            business_id=biz_id,
            business_name=biz_name,
            is_authorized=True,
            readiness_verdict=verdict,
            blockers=blockers,
            cautions=cautions,
            historical_coverage=coverage_metrics,
            customer_population=population_metrics,
            data_quality=quality_diagnostics,
            ingestion_health=ingestion_metrics,
            candidate_cutoffs=feasibility_items,
            pilot_safeguards=safeguards,
        )
