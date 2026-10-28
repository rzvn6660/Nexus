"""Unit tests for Phase 1B Historical Customer Churn-Risk Validation."""

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from app.analytics.core.context import AnalysisContext
from app.analytics.customer.cadence import CadenceConfig, CadenceRiskTier
from app.analytics.customer.validation import (
    HistoricalCadenceValidator,
    compute_wilson_score_interval,
)
from app.models.customer import Customer
from app.models.sale import Sale
from app.models.tenant import Business, IngestionJob, Organization, UploadedDataset
from sqlalchemy.orm import Session


def test_wilson_score_interval_properties():
    """Verify Wilson score confidence interval mathematical properties and bounds."""
    # Zero sample size returns None
    lower, upper = compute_wilson_score_interval(0, 0)
    assert lower is None
    assert upper is None

    # Known sample: 20 successes in 100 trials (p = 0.20)
    lower, upper = compute_wilson_score_interval(20, 100)
    assert lower is not None and upper is not None
    assert 0.0 <= lower < 0.20 < upper <= 1.0
    assert lower == pytest.approx(0.1332, abs=0.01)
    assert upper == pytest.approx(0.2888, abs=0.01)

    # Extreme sample: 0 successes in 50 trials (p = 0.0) -> lower must be 0.0
    lower_zero, upper_zero = compute_wilson_score_interval(0, 50)
    assert lower_zero == 0.0
    assert upper_zero is not None and upper_zero > 0.0

    # Extreme sample: 50 successes in 50 trials (p = 1.0) -> upper must be 1.0
    lower_one, upper_one = compute_wilson_score_interval(50, 50)
    assert lower_one is not None and lower_one < 1.0
    assert upper_one == 1.0


def test_temporal_feature_outcome_separation_and_no_leakage(db_session: Session):
    """
    Verify strict temporal separation:
    - Orders <= cutoff determine cadence features and risk tier.
    - Orders in [cutoff, cutoff + buffer] are in the buffer window.
    - Orders in [cutoff + buffer, cutoff + buffer + horizon] determine outcome.
    - Future outcome orders do NOT leak into historical cadence features.
    """
    c = Customer(
        customer_code="CUST-TEMP-01",
        name="Temporal Separation Buyer",
        email="temp@sep.com",
        city="Denver",
        customer_segment="Retail",
        acquisition_date=date(2023, 1, 1),
    )
    db_session.add(c)
    db_session.flush()

    # Historical orders (Jan 1, Jan 11) -> Cadence = 10.0 days
    s_hist1 = Sale(
        transaction_number="TXN-H-01",
        customer_id=c.id,
        transaction_date=datetime(2023, 1, 1, 12, 0, tzinfo=UTC),
        status="completed",
        subtotal=Decimal("50.00"),
        total_amount=Decimal("50.00"),
    )
    s_hist2 = Sale(
        transaction_number="TXN-H-02",
        customer_id=c.id,
        transaction_date=datetime(2023, 1, 11, 12, 0, tzinfo=UTC),
        status="completed",
        subtotal=Decimal("50.00"),
        total_amount=Decimal("50.00"),
    )

    # Future order inside the outcome horizon (March 1)
    s_future = Sale(
        transaction_number="TXN-F-01",
        customer_id=c.id,
        transaction_date=datetime(2023, 3, 1, 12, 0, tzinfo=UTC),
        status="completed",
        subtotal=Decimal("50.00"),
        total_amount=Decimal("50.00"),
    )
    # Extra future order far out (July 1) to ensure full complete follow-up
    s_far = Sale(
        transaction_number="TXN-FAR-01",
        customer_id=c.id,
        transaction_date=datetime(2023, 7, 1, 12, 0, tzinfo=UTC),
        status="completed",
        subtotal=Decimal("50.00"),
        total_amount=Decimal("50.00"),
    )
    db_session.add_all([s_hist1, s_hist2, s_future, s_far])
    db_session.commit()

    # Cutoff at Jan 31 (20 days after last historical order)
    # Recency at cutoff = 20.0 days -> Cadence Ratio = 20.0 / 10.0 = 2.0x (HIGH tier)
    # Buffer = 7 days (Feb 1 to Feb 7)
    # Horizon = 60 days (Feb 7 to April 8)
    cutoff = datetime(2023, 1, 31, 12, 0, tzinfo=UTC)
    result = HistoricalCadenceValidator.evaluate_cutoff(
        session=db_session,
        cutoff_date=cutoff,
        buffer_days=7,
        horizon_days=60,
    )

    assert result.is_complete_followup is True
    assert result.total_customers_evaluated == 1
    assert result.scored_customers_count == 1

    rec = result.customer_records[0]
    # 1. Feature verification: March 1 order did NOT leak into historical features
    assert rec.eligible_historical_orders == 2
    assert rec.baseline_cadence_days == 10.0
    assert rec.days_since_last_purchase == 20.0
    assert rec.cadence_ratio == 2.0
    assert rec.risk_tier == CadenceRiskTier.HIGH

    # 2. Outcome verification: March 1 order was correctly detected inside outcome window
    assert rec.future_orders_in_horizon == 1
    assert rec.observed_repeat_purchase is True
    assert rec.outcome_no_purchase is False


def test_buffer_window_and_horizon_boundaries(db_session: Session):
    """
    Verify that orders occurring strictly inside the buffer window [cutoff, cutoff + buffer]
    do NOT count as an outcome in the evaluation horizon.
    """
    c = Customer(
        customer_code="CUST-BUFFER-01",
        name="Buffer Boundary Buyer",
        email="buffer@test.com",
        city="Seattle",
        customer_segment="Corporate",
        acquisition_date=date(2023, 1, 1),
    )
    db_session.add(c)
    db_session.flush()

    # Historical orders: Jan 1, Jan 15
    s1 = Sale(
        transaction_number="TXN-BUF-01",
        customer_id=c.id,
        transaction_date=datetime(2023, 1, 1, 0, 0, tzinfo=UTC),
        status="completed",
        subtotal=Decimal("100.00"),
        total_amount=Decimal("100.00"),
    )
    s2 = Sale(
        transaction_number="TXN-BUF-02",
        customer_id=c.id,
        transaction_date=datetime(2023, 1, 15, 0, 0, tzinfo=UTC),
        status="completed",
        subtotal=Decimal("100.00"),
        total_amount=Decimal("100.00"),
    )
    # Order placed during the buffer window (Jan 22, inside 7-day buffer Jan 20 to Jan 27)
    s_buffer = Sale(
        transaction_number="TXN-BUF-IN-GAP",
        customer_id=c.id,
        transaction_date=datetime(2023, 1, 22, 0, 0, tzinfo=UTC),
        status="completed",
        subtotal=Decimal("100.00"),
        total_amount=Decimal("100.00"),
    )
    # Complete follow-up anchor
    s_anchor = Sale(
        transaction_number="TXN-BUF-ANCHOR",
        customer_id=c.id,
        transaction_date=datetime(2023, 6, 1, 0, 0, tzinfo=UTC),
        status="completed",
        subtotal=Decimal("100.00"),
        total_amount=Decimal("100.00"),
    )
    db_session.add_all([s1, s2, s_buffer, s_anchor])
    db_session.commit()

    cutoff = datetime(2023, 1, 20, 0, 0, tzinfo=UTC)
    result = HistoricalCadenceValidator.evaluate_cutoff(
        session=db_session,
        cutoff_date=cutoff,
        buffer_days=7,
        horizon_days=60,
    )

    rec = result.customer_records[0]
    # Order on Jan 22 was inside buffer, NOT in horizon (Jan 27 to March 28)
    assert rec.future_orders_in_horizon == 0
    assert rec.observed_repeat_purchase is False
    assert rec.outcome_no_purchase is True


def test_outcome_transaction_status_eligibility(db_session: Session):
    """
    Verify that cancelled, refunded, or pending orders inside the outcome horizon
    do NOT count as a repeat purchase event.
    """
    c = Customer(
        customer_code="CUST-STATUS-OUT",
        name="Status Outcome Buyer",
        email="statusout@test.com",
        city="Portland",
        customer_segment="Retail",
        acquisition_date=date(2023, 1, 1),
    )
    db_session.add(c)
    db_session.flush()

    s1 = Sale(
        transaction_number="TXN-SO-01",
        customer_id=c.id,
        transaction_date=datetime(2023, 1, 1, 10, 0, tzinfo=UTC),
        status="completed",
        subtotal=Decimal("50.00"),
        total_amount=Decimal("50.00"),
    )
    s2 = Sale(
        transaction_number="TXN-SO-02",
        customer_id=c.id,
        transaction_date=datetime(2023, 1, 11, 10, 0, tzinfo=UTC),
        status="completed",
        subtotal=Decimal("50.00"),
        total_amount=Decimal("50.00"),
    )

    # Future orders in outcome window: cancelled and refunded
    s_canc = Sale(
        transaction_number="TXN-SO-CANC",
        customer_id=c.id,
        transaction_date=datetime(2023, 2, 15, 10, 0, tzinfo=UTC),
        status="cancelled",
        subtotal=Decimal("50.00"),
        total_amount=Decimal("50.00"),
    )
    s_ref = Sale(
        transaction_number="TXN-SO-REF",
        customer_id=c.id,
        transaction_date=datetime(2023, 2, 20, 10, 0, tzinfo=UTC),
        status="refunded",
        subtotal=Decimal("50.00"),
        total_amount=Decimal("50.00"),
    )
    s_anchor = Sale(
        transaction_number="TXN-SO-ANCHOR",
        customer_id=c.id,
        transaction_date=datetime(2023, 6, 1, 10, 0, tzinfo=UTC),
        status="completed",
        subtotal=Decimal("50.00"),
        total_amount=Decimal("50.00"),
    )
    db_session.add_all([s1, s2, s_canc, s_ref, s_anchor])
    db_session.commit()

    cutoff = datetime(2023, 1, 21, 10, 0, tzinfo=UTC)
    result = HistoricalCadenceValidator.evaluate_cutoff(
        session=db_session,
        cutoff_date=cutoff,
        buffer_days=3,
        horizon_days=60,
    )

    rec = result.customer_records[0]
    # Cancelled and refunded orders must NOT count as a repeat purchase
    assert rec.future_orders_in_horizon == 0
    assert rec.observed_repeat_purchase is False
    assert rec.outcome_no_purchase is True


def test_tenant_isolation_in_features_and_outcomes(db_session: Session):
    """
    Verify multi-tenant isolation:
    - Customer A and sales in Tenant 1
    - Customer B and sales in Tenant 2
    - Cross-tenant sales never satisfy future outcome horizon for another tenant.
    """
    c1 = Customer(
        customer_code="CUST-TEN-A",
        business_id="biz-alpha",
        name="Alpha Customer",
        email="alpha@test.com",
        city="Austin",
        customer_segment="Corporate",
        acquisition_date=date(2023, 1, 1),
    )
    c2 = Customer(
        customer_code="CUST-TEN-B",
        business_id="biz-beta",
        name="Beta Customer",
        email="beta@test.com",
        city="Austin",
        customer_segment="Corporate",
        acquisition_date=date(2023, 1, 1),
    )
    db_session.add_all([c1, c2])
    db_session.flush()

    # Historical sales for c1 in biz-alpha
    s1_1 = Sale(
        transaction_number="TXN-ALPHA-01",
        business_id="biz-alpha",
        customer_id=c1.id,
        transaction_date=datetime(2023, 1, 1, 10, 0, tzinfo=UTC),
        status="completed",
        subtotal=Decimal("100.00"),
        total_amount=Decimal("100.00"),
    )
    s1_2 = Sale(
        transaction_number="TXN-ALPHA-02",
        business_id="biz-alpha",
        customer_id=c1.id,
        transaction_date=datetime(2023, 1, 11, 10, 0, tzinfo=UTC),
        status="completed",
        subtotal=Decimal("100.00"),
        total_amount=Decimal("100.00"),
    )
    # Cross-tenant intrusion: Sale with biz-beta in future horizon pointing to c1.id
    s_intruder = Sale(
        transaction_number="TXN-BETA-FUTURE-INTRUDER",
        business_id="biz-beta",
        customer_id=c1.id,
        transaction_date=datetime(2023, 2, 15, 10, 0, tzinfo=UTC),
        status="completed",
        subtotal=Decimal("100.00"),
        total_amount=Decimal("100.00"),
    )
    s_anchor = Sale(
        transaction_number="TXN-ALPHA-ANCHOR",
        business_id="biz-alpha",
        customer_id=c1.id,
        transaction_date=datetime(2023, 6, 1, 10, 0, tzinfo=UTC),
        status="completed",
        subtotal=Decimal("100.00"),
        total_amount=Decimal("100.00"),
    )
    db_session.add_all([s1_1, s1_2, s_intruder, s_anchor])
    db_session.commit()

    ctx = AnalysisContext(business_id="biz-alpha")
    cutoff = datetime(2023, 1, 21, 10, 0, tzinfo=UTC)
    result = HistoricalCadenceValidator.evaluate_cutoff(
        session=db_session,
        context=ctx,
        cutoff_date=cutoff,
        buffer_days=3,
        horizon_days=60,
    )

    assert result.total_customers_evaluated == 1
    rec = result.customer_records[0]
    assert rec.customer_code == "CUST-TEN-A"
    # The intruder sale belongs to biz-beta, so it cannot count as an outcome for biz-alpha
    assert rec.future_orders_in_horizon == 0
    assert rec.outcome_no_purchase is True


def test_right_censoring_detection_on_incomplete_followup(db_session: Session):
    """
    Verify that when database records do not extend through the full outcome horizon,
    the cutoff is flagged as right-censored with an explicit reason.
    """
    c = Customer(
        customer_code="CUST-CENSOR",
        name="Censored Followup Buyer",
        email="censor@test.com",
        city="Chicago",
        customer_segment="Retail",
        acquisition_date=date(2023, 1, 1),
    )
    db_session.add(c)
    db_session.flush()

    # Database only has data up to Feb 10
    s1 = Sale(
        transaction_number="TXN-CEN-01",
        customer_id=c.id,
        transaction_date=datetime(2023, 1, 1, 10, 0, tzinfo=UTC),
        status="completed",
        subtotal=Decimal("50.00"),
        total_amount=Decimal("50.00"),
    )
    s2 = Sale(
        transaction_number="TXN-CEN-02",
        customer_id=c.id,
        transaction_date=datetime(2023, 2, 10, 10, 0, tzinfo=UTC),
        status="completed",
        subtotal=Decimal("50.00"),
        total_amount=Decimal("50.00"),
    )
    db_session.add_all([s1, s2])
    db_session.commit()

    # Cutoff at Feb 1 with 60-day horizon -> Outcome window ends in April, but DB ends Feb 10!
    cutoff = datetime(2023, 2, 1, 10, 0, tzinfo=UTC)
    result = HistoricalCadenceValidator.evaluate_cutoff(
        session=db_session,
        cutoff_date=cutoff,
        buffer_days=3,
        horizon_days=60,
    )

    assert result.is_complete_followup is False
    assert result.censoring_reason is not None
    assert "precedes outcome window end" in result.censoring_reason
    assert any("Outcome follow-up was right-censored" in lim for lim in result.limitations)


def test_classification_metrics_confusion_matrix_and_lift(db_session: Session):
    """
    Verify exact deterministic computation of confusion matrices, precision,
    recall, specificity, F1-score, and lift across multiple customers.
    """
    # Create 4 customers:
    # C1: Critical tier, observed no purchase (TP for Critical)
    # C2: Critical tier, observed repeat purchase (FP for Critical)
    # C3: Low tier, observed no purchase (FN for Critical, FP for Low)
    # C4: Low tier, observed repeat purchase (TN for Critical)
    customers = []
    for i in range(1, 5):
        c = Customer(
            customer_code=f"CUST-METRIC-{i}",
            name=f"Metric Customer {i}",
            email=f"metric{i}@test.com",
            city="Chicago",
            customer_segment="Corporate",
            acquisition_date=date(2023, 1, 1),
        )
        db_session.add(c)
        customers.append(c)
    db_session.flush()

    # All customers had 2 historical orders 10.0 days apart (Jan 1, Jan 11) -> Cadence = 10.0 days
    for c in customers:
        s1 = Sale(
            transaction_number=f"TXN-M1-{c.id}",
            customer_id=c.id,
            transaction_date=datetime(2023, 1, 1, 0, 0, tzinfo=UTC),
            status="completed",
            subtotal=Decimal("50.00"),
            total_amount=Decimal("50.00"),
        )
        s2 = Sale(
            transaction_number=f"TXN-M2-{c.id}",
            customer_id=c.id,
            transaction_date=datetime(2023, 1, 11, 0, 0, tzinfo=UTC),
            status="completed",
            subtotal=Decimal("50.00"),
            total_amount=Decimal("50.00"),
        )
        db_session.add_all([s1, s2])

    # For C1 and C2, add a purchase that made them recent at an earlier date, or adjust cutoff:
    # Better: set C1 and C2 to have last order on Jan 11, evaluate at March 1 (elapsed 49 days -> ratio 4.9x -> CRITICAL)
    # For C3 and C4, add an order on Feb 25 (elapsed 4 days -> ratio 0.4x -> LOW)
    for c in [customers[2], customers[3]]:
        s_recent = Sale(
            transaction_number=f"TXN-M-RECENT-{c.id}",
            customer_id=c.id,
            transaction_date=datetime(2023, 2, 25, 0, 0, tzinfo=UTC),
            status="completed",
            subtotal=Decimal("50.00"),
            total_amount=Decimal("50.00"),
        )
        db_session.add(s_recent)

    # Future orders in outcome horizon (March 5 to May 5):
    # C2 places a repeat order
    # C4 places a repeat order
    # C1 and C3 place NO repeat orders
    s_c2_fut = Sale(
        transaction_number="TXN-C2-FUT",
        customer_id=customers[1].id,
        transaction_date=datetime(2023, 3, 20, 0, 0, tzinfo=UTC),
        status="completed",
        subtotal=Decimal("50.00"),
        total_amount=Decimal("50.00"),
    )
    s_c4_fut = Sale(
        transaction_number="TXN-C4-FUT",
        customer_id=customers[3].id,
        transaction_date=datetime(2023, 3, 20, 0, 0, tzinfo=UTC),
        status="completed",
        subtotal=Decimal("50.00"),
        total_amount=Decimal("50.00"),
    )
    s_anchor = Sale(
        transaction_number="TXN-M-ANCHOR",
        customer_id=customers[0].id,
        transaction_date=datetime(2023, 6, 1, 0, 0, tzinfo=UTC),
        status="completed",
        subtotal=Decimal("50.00"),
        total_amount=Decimal("50.00"),
    )
    db_session.add_all([s_c2_fut, s_c4_fut, s_anchor])
    db_session.commit()

    cutoff = datetime(2023, 3, 1, 0, 0, tzinfo=UTC)
    result = HistoricalCadenceValidator.evaluate_cutoff(
        session=db_session,
        cutoff_date=cutoff,
        buffer_days=3,
        horizon_days=60,
    )

    assert result.scored_customers_count == 4
    # Baseline no-purchase count: C1 and C3 had no purchase -> 2 out of 4 = 50.0%
    assert result.baseline_no_purchase_rate == 0.50

    # Critical tier metrics:
    # 2 customers in Critical (C1 and C2). C1 had no purchase, C2 had purchase.
    # Critical Precision = 1 / 2 = 50.0%
    crit_cm = result.confusion_matrices["critical"]
    assert crit_cm.tp == 1  # C1
    assert crit_cm.fp == 1  # C2
    assert crit_cm.fn == 1  # C3
    assert crit_cm.tn == 1  # C4
    assert crit_cm.precision == 0.50
    assert crit_cm.recall == 0.50
    assert crit_cm.accuracy == 0.50

    # Lift = 0.50 / 0.50 = 1.0
    assert result.critical_lift == 1.0


def test_empty_dataset_and_undefined_metrics(db_session: Session):
    """
    Verify that an empty customer cohort returns well-defined empty schemas
    without encountering division by zero.
    """
    cutoff = datetime(2023, 1, 1, 0, 0, tzinfo=UTC)
    result = HistoricalCadenceValidator.evaluate_cutoff(
        session=db_session,
        cutoff_date=cutoff,
        buffer_days=7,
        horizon_days=60,
    )

    assert result.total_customers_evaluated == 0
    assert result.scored_customers_count == 0
    assert result.baseline_no_purchase_rate is None
    assert result.critical_precision is None
    assert result.critical_lift is None
    assert len(result.customer_records) == 0


def test_multi_cutoff_validation_summary_and_overlapping_notice(db_session: Session):
    """
    Verify multi-cutoff execution:
    - Runs multiple chronological cutoffs.
    - Aggregates pooled metrics.
    - Includes explicit overlapping cohort notice.
    """
    c = Customer(
        customer_code="CUST-MULTI-CUT",
        name="Multi Cutoff Customer",
        email="multi@test.com",
        city="Dallas",
        customer_segment="Retail",
        acquisition_date=date(2023, 1, 1),
    )
    db_session.add(c)
    db_session.flush()

    s1 = Sale(
        transaction_number="TXN-MC-01",
        customer_id=c.id,
        transaction_date=datetime(2023, 1, 1, 10, 0, tzinfo=UTC),
        status="completed",
        subtotal=Decimal("100.00"),
        total_amount=Decimal("100.00"),
    )
    s2 = Sale(
        transaction_number="TXN-MC-02",
        customer_id=c.id,
        transaction_date=datetime(2023, 1, 15, 10, 0, tzinfo=UTC),
        status="completed",
        subtotal=Decimal("100.00"),
        total_amount=Decimal("100.00"),
    )
    # Long future anchor ensuring complete follow-up across cutoffs
    s_anchor = Sale(
        transaction_number="TXN-MC-ANCHOR",
        customer_id=c.id,
        transaction_date=datetime(2023, 10, 1, 10, 0, tzinfo=UTC),
        status="completed",
        subtotal=Decimal("100.00"),
        total_amount=Decimal("100.00"),
    )
    db_session.add_all([s1, s2, s_anchor])
    db_session.commit()

    cutoffs = [
        datetime(2023, 2, 1, 10, 0, tzinfo=UTC),
        datetime(2023, 3, 1, 10, 0, tzinfo=UTC),
        datetime(2023, 4, 1, 10, 0, tzinfo=UTC),
    ]

    summary = HistoricalCadenceValidator.evaluate_multi_cutoff(
        session=db_session,
        cutoff_dates=cutoffs,
        buffer_days=3,
        horizon_days=30,
    )

    assert summary.cutoffs_evaluated == 3
    assert summary.complete_cutoffs_count == 3
    assert summary.incomplete_cutoffs_count == 0
    assert summary.total_scored_observations == 3
    assert "statistical dependence" in summary.overlapping_cohort_notice
    assert len(summary.cutoff_results) == 3


def test_insufficient_history_customers_tracked_separately_from_scored_metrics(
    db_session: Session,
):
    """
    Verify that customers with insufficient history (e.g. one-time buyers without fallback)
    are tracked in cohort totals and outcome records, but do not distort the scored risk-tier metrics.
    """
    # Customer 1: Repeat buyer (scored)
    c_scored = Customer(
        customer_code="CUST-SCORED",
        name="Scored Customer",
        email="scored@test.com",
        city="Miami",
        customer_segment="Corporate",
        acquisition_date=date(2023, 1, 1),
    )
    # Customer 2: One-time buyer (insufficient history when fallback disabled)
    c_insuff = Customer(
        customer_code="CUST-INSUFF",
        name="Insufficient History Customer",
        email="insuff@test.com",
        city="Miami",
        customer_segment="Corporate",
        acquisition_date=date(2023, 1, 1),
    )
    db_session.add_all([c_scored, c_insuff])
    db_session.flush()

    s1 = Sale(
        transaction_number="TXN-SC-01",
        customer_id=c_scored.id,
        transaction_date=datetime(2023, 1, 1, 10, 0, tzinfo=UTC),
        status="completed",
        subtotal=Decimal("50.00"),
        total_amount=Decimal("50.00"),
    )
    s2 = Sale(
        transaction_number="TXN-SC-02",
        customer_id=c_scored.id,
        transaction_date=datetime(2023, 1, 15, 10, 0, tzinfo=UTC),
        status="completed",
        subtotal=Decimal("50.00"),
        total_amount=Decimal("50.00"),
    )
    s_single = Sale(
        transaction_number="TXN-IN-01",
        customer_id=c_insuff.id,
        transaction_date=datetime(2023, 1, 10, 10, 0, tzinfo=UTC),
        status="completed",
        subtotal=Decimal("50.00"),
        total_amount=Decimal("50.00"),
    )
    s_anchor = Sale(
        transaction_number="TXN-IN-ANCHOR",
        customer_id=c_scored.id,
        transaction_date=datetime(2023, 6, 1, 10, 0, tzinfo=UTC),
        status="completed",
        subtotal=Decimal("50.00"),
        total_amount=Decimal("50.00"),
    )
    db_session.add_all([s1, s2, s_single, s_anchor])
    db_session.commit()

    cfg = CadenceConfig(use_segment_fallback=False)
    cutoff = datetime(2023, 1, 25, 10, 0, tzinfo=UTC)
    result = HistoricalCadenceValidator.evaluate_cutoff(
        session=db_session,
        cutoff_date=cutoff,
        buffer_days=3,
        horizon_days=60,
        cadence_config=cfg,
    )

    assert result.total_customers_evaluated == 2
    assert result.scored_customers_count == 1
    assert result.insufficient_history_count == 1
    assert result.repeat_buyers_count == 1
    assert result.one_time_buyers_count == 1

    # Insufficient history customer is NOT counted as low risk in evaluation metrics
    assert result.tier_performances["low"].customer_count == 1
    assert result.tier_performances["insufficient_history"].customer_count == 1

    # Both customers are present in customer_records
    assert len(result.customer_records) == 2
    rec_insuff = next(r for r in result.customer_records if r.customer_code == "CUST-INSUFF")
    assert rec_insuff.risk_tier == CadenceRiskTier.INSUFFICIENT_HISTORY
    assert rec_insuff.is_repeat_buyer is False
    assert rec_insuff.outcome_no_purchase is True
    # Lift for insufficient_history must remain None (unscored cohort)
    assert result.tier_performances["insufficient_history"].lift_vs_baseline is None

    # Safety invariant: even when segment fallback is explicitly enabled, the one-time buyer is NOT scored as low/overdue
    res_fallback_enabled = HistoricalCadenceValidator.evaluate_cutoff(
        session=db_session,
        cutoff_date=cutoff,
        buffer_days=3,
        horizon_days=60,
        cadence_config=CadenceConfig(use_segment_fallback=True),
    )
    assert res_fallback_enabled.scored_customers_count == 1
    assert res_fallback_enabled.insufficient_history_count == 1
    rec_fb_insuff = next(r for r in res_fallback_enabled.customer_records if r.customer_code == "CUST-INSUFF")
    assert rec_fb_insuff.risk_tier == CadenceRiskTier.INSUFFICIENT_HISTORY


def test_authoritative_ingestion_watermark_enforcement(db_session: Session):
    """
    Verify that an authoritative ingestion watermark governs follow-up completeness:
    - Watermark before outcome window end -> right-censored (incomplete).
    - Watermark at or after outcome window end -> verified complete.
    """
    c = Customer(
        customer_code="CUST-WATERMARK",
        name="Watermark Test Buyer",
        email="wm@test.com",
        city="Denver",
        customer_segment="Corporate",
        acquisition_date=date(2023, 1, 1),
    )
    db_session.add(c)
    db_session.flush()

    s1 = Sale(
        transaction_number="TXN-WM-01",
        customer_id=c.id,
        transaction_date=datetime(2023, 1, 1, 10, 0, tzinfo=UTC),
        status="completed",
        subtotal=Decimal("100.00"),
        total_amount=Decimal("100.00"),
    )
    s2 = Sale(
        transaction_number="TXN-WM-02",
        customer_id=c.id,
        transaction_date=datetime(2023, 1, 15, 10, 0, tzinfo=UTC),
        status="completed",
        subtotal=Decimal("100.00"),
        total_amount=Decimal("100.00"),
    )
    # Stray order in database far into the future (e.g. July)
    s_far = Sale(
        transaction_number="TXN-WM-FAR",
        customer_id=c.id,
        transaction_date=datetime(2023, 7, 1, 10, 0, tzinfo=UTC),
        status="completed",
        subtotal=Decimal("100.00"),
        total_amount=Decimal("100.00"),
    )
    db_session.add_all([s1, s2, s_far])
    db_session.commit()

    cutoff = datetime(2023, 1, 31, 10, 0, tzinfo=UTC)
    # Outcome window: Feb 7 to April 8 (buffer=7, horizon=60)
    # Case 1: Ingestion pipeline watermark is Feb 28 (before April 8)
    res_censored = HistoricalCadenceValidator.evaluate_cutoff(
        session=db_session,
        cutoff_date=cutoff,
        buffer_days=7,
        horizon_days=60,
        ingestion_watermark=datetime(2023, 2, 28, 23, 59, tzinfo=UTC),
    )
    assert res_censored.is_complete_followup is False
    assert res_censored.is_followup_verified is True
    assert res_censored.followup_status == "incomplete_censored"
    assert "Authoritative ingestion watermark" in res_censored.censoring_reason

    # Case 2: Ingestion pipeline watermark is April 15 (after April 8)
    res_verified = HistoricalCadenceValidator.evaluate_cutoff(
        session=db_session,
        cutoff_date=cutoff,
        buffer_days=7,
        horizon_days=60,
        ingestion_watermark=datetime(2023, 4, 15, 23, 59, tzinfo=UTC),
    )
    assert res_verified.is_complete_followup is True
    assert res_verified.is_followup_verified is True
    assert res_verified.followup_status == "verified_complete"
    assert res_verified.censoring_reason is None


def test_in_flight_ingestion_job_marks_followup_incomplete(db_session: Session):
    """
    Verify that an in-flight or failed IngestionJob for the tenant marks the cutoff
    follow-up as incomplete_in_flight rather than falsely claiming completeness.
    """
    org = Organization(name="Ingestion Test Org", slug="ingestion-test-org")
    db_session.add(org)
    db_session.flush()

    biz = Business(organization_id=org.id, name="Ingestion Test Biz")
    db_session.add(biz)
    db_session.flush()

    ds = UploadedDataset(
        business_id=biz.id,
        organization_id=org.id,
        filename="sales_batch.csv",
        file_type="csv",
        storage_key="/storage/sales_batch.csv",
        file_size_bytes=1024,
    )
    db_session.add(ds)
    db_session.flush()

    # Active in-flight processing job
    job = IngestionJob(
        organization_id=org.id,
        business_id=biz.id,
        dataset_id=ds.id,
        status="PROCESSING",
    )
    db_session.add(job)

    c = Customer(
        customer_code="CUST-INFLIGHT",
        business_id=biz.id,
        name="Inflight Customer",
        email="inflight@test.com",
        city="Austin",
        customer_segment="Corporate",
        acquisition_date=date(2023, 1, 1),
    )
    db_session.add(c)
    db_session.flush()

    s1 = Sale(
        transaction_number="TXN-INF-01",
        business_id=biz.id,
        customer_id=c.id,
        transaction_date=datetime(2023, 1, 1, 10, 0, tzinfo=UTC),
        status="completed",
        subtotal=Decimal("50.00"),
        total_amount=Decimal("50.00"),
    )
    s2 = Sale(
        transaction_number="TXN-INF-02",
        business_id=biz.id,
        customer_id=c.id,
        transaction_date=datetime(2023, 6, 1, 10, 0, tzinfo=UTC),
        status="completed",
        subtotal=Decimal("50.00"),
        total_amount=Decimal("50.00"),
    )
    db_session.add_all([s1, s2])
    db_session.commit()

    ctx = AnalysisContext(business_id=biz.id)
    cutoff = datetime(2023, 1, 15, 10, 0, tzinfo=UTC)
    result = HistoricalCadenceValidator.evaluate_cutoff(
        session=db_session,
        context=ctx,
        cutoff_date=cutoff,
        buffer_days=3,
        horizon_days=60,
    )

    assert result.is_complete_followup is False
    assert result.is_followup_verified is False
    assert result.followup_status == "incomplete_in_flight"
    assert "in-flight data ingestion job detected" in result.censoring_reason


def test_unverified_completeness_flag_and_limitation(db_session: Session):
    """
    Verify that when no authoritative watermark is provided, follow-up is reported
    as unverified_complete with an explicit limitation warning.
    """
    c = Customer(
        customer_code="CUST-UNVERIFIED",
        name="Unverified Customer",
        email="unverified@test.com",
        city="Phoenix",
        customer_segment="Retail",
        acquisition_date=date(2023, 1, 1),
    )
    db_session.add(c)
    db_session.flush()

    s1 = Sale(
        transaction_number="TXN-UNV-01",
        customer_id=c.id,
        transaction_date=datetime(2023, 1, 1, 10, 0, tzinfo=UTC),
        status="completed",
        subtotal=Decimal("50.00"),
        total_amount=Decimal("50.00"),
    )
    s2 = Sale(
        transaction_number="TXN-UNV-02",
        customer_id=c.id,
        transaction_date=datetime(2023, 1, 10, 10, 0, tzinfo=UTC),
        status="completed",
        subtotal=Decimal("50.00"),
        total_amount=Decimal("50.00"),
    )
    s_far = Sale(
        transaction_number="TXN-UNV-FAR",
        customer_id=c.id,
        transaction_date=datetime(2023, 8, 1, 10, 0, tzinfo=UTC),
        status="completed",
        subtotal=Decimal("50.00"),
        total_amount=Decimal("50.00"),
    )
    db_session.add_all([s1, s2, s_far])
    db_session.commit()

    cutoff = datetime(2023, 1, 20, 10, 0, tzinfo=UTC)
    result = HistoricalCadenceValidator.evaluate_cutoff(
        session=db_session,
        cutoff_date=cutoff,
        buffer_days=7,
        horizon_days=60,
    )

    assert result.is_complete_followup is True
    assert result.is_followup_verified is False
    assert result.followup_status == "unverified_complete"
    assert any("Follow-up completeness is unverified" in lim for lim in result.limitations)
