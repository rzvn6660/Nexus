"""Unit tests for Phase 1A Customer Purchase Cadence Analyzer."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from app.analytics.core.context import AnalysisContext
from app.analytics.customer.cadence import (
    CadenceConfig,
    CadenceRiskTier,
    CustomerCadenceAnalyzer,
)
from app.models.customer import Customer
from app.models.product import Product
from app.models.sale import Sale
from app.models.sale_item import SaleItem
from pydantic import ValidationError
from sqlalchemy.orm import Session


def test_known_purchase_intervals_and_exact_expected_values(db_session: Session):
    """
    Verify exact mathematical computation of mean, median, sample std,
    and cadence ratio for known purchase dates.
    """
    c = Customer(
        customer_code="CUST-CAD-01",
        name="Precise Cadence Buyer",
        email="precise@cadence.com",
        city="Chicago",
        customer_segment="Corporate",
        acquisition_date=date(2023, 1, 1),
    )
    db_session.add(c)
    db_session.flush()

    # Day 0, Day 10, Day 30, Day 60
    # Intervals: 10.0 days, 20.0 days, 30.0 days
    # Mean: 20.0, Median: 20.0, Sample Std: 10.0
    dates = [
        datetime(2023, 1, 1, 12, 0, tzinfo=UTC),
        datetime(2023, 1, 11, 12, 0, tzinfo=UTC),
        datetime(2023, 1, 31, 12, 0, tzinfo=UTC),
        datetime(2023, 3, 2, 12, 0, tzinfo=UTC),
    ]
    for idx, d in enumerate(dates):
        s = Sale(
            transaction_number=f"TXN-CAD-01-{idx + 1}",
            customer_id=c.id,
            transaction_date=d,
            status="completed",
            subtotal=Decimal("100.00"),
            total_amount=Decimal("100.00"),
        )
        db_session.add(s)
    db_session.commit()

    # Evaluate at Day 80 (20.0 days after Day 60) -> recency = 20.0 days -> ratio = 1.0 (LOW)
    cutoff = datetime(2023, 3, 22, 12, 0, tzinfo=UTC)
    summary = CustomerCadenceAnalyzer.evaluate(db_session, as_of_date=cutoff)

    assert summary.total_customers_evaluated == 1
    assert summary.customers_scored == 1
    assert summary.insufficient_history_count == 0

    rec = summary.records[0]
    assert rec.customer_code == "CUST-CAD-01"
    assert rec.eligible_order_count == 4
    assert rec.mean_ipi_days == 20.0
    assert rec.median_ipi_days == 20.0
    assert rec.std_ipi_days == 10.0
    assert rec.last_purchase_date == datetime(2023, 3, 2, 12, 0, tzinfo=UTC)
    assert rec.days_since_last_purchase == 20.0
    assert rec.baseline_cadence_days == 20.0
    assert rec.cadence_source == "individual"
    assert rec.cadence_ratio == 1.0
    assert rec.risk_tier == CadenceRiskTier.LOW
    assert "within expected purchase cadence" in rec.explanation.summary


def test_one_time_buyers_and_insufficient_history(db_session: Session):
    """
    Verify that single-purchase customers receive an explicit INSUFFICIENT_HISTORY
    state when no segment fallback is available.
    """
    c = Customer(
        customer_code="CUST-ONETIME",
        name="One-Time Shopper",
        email="onetime@test.com",
        city="Denver",
        customer_segment="Retail",
        acquisition_date=date(2023, 2, 1),
    )
    db_session.add(c)
    db_session.flush()

    s = Sale(
        transaction_number="TXN-ONETIME-01",
        customer_id=c.id,
        transaction_date=datetime(2023, 2, 10, 10, 0, tzinfo=UTC),
        status="completed",
        subtotal=Decimal("50.00"),
        total_amount=Decimal("50.00"),
    )
    db_session.add(s)
    db_session.commit()

    cfg = CadenceConfig(use_segment_fallback=False)
    cutoff = datetime(2023, 3, 10, 10, 0, tzinfo=UTC)
    summary = CustomerCadenceAnalyzer.evaluate(db_session, as_of_date=cutoff, config=cfg)

    assert summary.total_customers_evaluated == 1
    assert summary.customers_scored == 0
    assert summary.insufficient_history_count == 1
    assert summary.risk_tier_counts["insufficient_history"] == 1

    rec = summary.records[0]
    assert rec.eligible_order_count == 1
    assert rec.mean_ipi_days is None
    assert rec.std_ipi_days is None
    assert rec.median_ipi_days is None
    assert rec.days_since_last_purchase == 28.0
    assert rec.baseline_cadence_days is None
    assert rec.cadence_source == "insufficient_history"
    assert rec.cadence_ratio is None
    assert rec.risk_tier == CadenceRiskTier.INSUFFICIENT_HISTORY
    assert "insufficient repeat purchase history" in rec.explanation.summary


def test_identical_order_dates_and_zero_variance_intervals(db_session: Session):
    """
    Verify handling of duplicate order timestamps (zero interval) and constant intervals (zero variance).
    """
    # Customer 1: Duplicate order timestamps (interval = 0.0)
    c1 = Customer(
        customer_code="CUST-DUP",
        name="Duplicate Order Buyer",
        email="dup@test.com",
        city="Austin",
        customer_segment="Wholesale",
        acquisition_date=date(2023, 1, 1),
    )
    # Customer 2: Exactly 7 days between every purchase (zero variance in intervals)
    c2 = Customer(
        customer_code="CUST-CONST",
        name="Constant Interval Buyer",
        email="const@test.com",
        city="Dallas",
        customer_segment="Retail",
        acquisition_date=date(2023, 1, 1),
    )
    db_session.add_all([c1, c2])
    db_session.flush()

    same_time = datetime(2023, 1, 15, 14, 30, tzinfo=UTC)
    s1 = Sale(
        transaction_number="TXN-DUP-01",
        customer_id=c1.id,
        transaction_date=same_time,
        status="completed",
        subtotal=Decimal("40.00"),
        total_amount=Decimal("40.00"),
    )
    s2 = Sale(
        transaction_number="TXN-DUP-02",
        customer_id=c1.id,
        transaction_date=same_time,
        status="completed",
        subtotal=Decimal("60.00"),
        total_amount=Decimal("60.00"),
    )

    const_dates = [
        datetime(2023, 1, 1, 10, 0, tzinfo=UTC),
        datetime(2023, 1, 8, 10, 0, tzinfo=UTC),
        datetime(2023, 1, 15, 10, 0, tzinfo=UTC),
    ]
    sales_c2 = [
        Sale(
            transaction_number=f"TXN-CONST-{i + 1}",
            customer_id=c2.id,
            transaction_date=d,
            status="completed",
            subtotal=Decimal("50.00"),
            total_amount=Decimal("50.00"),
        )
        for i, d in enumerate(const_dates)
    ]

    db_session.add_all([s1, s2, *sales_c2])
    db_session.commit()

    cfg = CadenceConfig(use_segment_fallback=False)
    cutoff = datetime(2023, 1, 22, 10, 0, tzinfo=UTC)
    summary = CustomerCadenceAnalyzer.evaluate(db_session, as_of_date=cutoff, config=cfg)

    rec_c1 = next(r for r in summary.records if r.customer_code == "CUST-DUP")
    assert rec_c1.eligible_order_count == 2
    assert rec_c1.mean_ipi_days == 0.0
    assert rec_c1.median_ipi_days == 0.0
    assert rec_c1.cadence_ratio is None
    assert rec_c1.risk_tier == CadenceRiskTier.INSUFFICIENT_HISTORY

    rec_c2 = next(r for r in summary.records if r.customer_code == "CUST-CONST")
    assert rec_c2.eligible_order_count == 3
    assert rec_c2.mean_ipi_days == 7.0
    assert rec_c2.median_ipi_days == 7.0
    assert rec_c2.std_ipi_days == 0.0  # Zero variance handled smoothly
    assert rec_c2.days_since_last_purchase == 7.0
    assert rec_c2.cadence_ratio == 1.0
    assert rec_c2.risk_tier == CadenceRiskTier.LOW


def test_empty_transaction_history_and_inactive_customers(db_session: Session):
    """
    Verify that customers with zero purchases receive an explicit empty-history state,
    and long-inactive customers receive a critical inactivity rating.
    """
    c_empty = Customer(
        customer_code="CUST-NO-ORDERS",
        name="Zero Orders Customer",
        email="noorders@test.com",
        city="Miami",
        customer_segment="Retail",
        acquisition_date=date(2023, 1, 1),
    )
    c_dormant = Customer(
        customer_code="CUST-DORMANT",
        name="Long Dormant Customer",
        email="dormant@test.com",
        city="Tampa",
        customer_segment="Corporate",
        acquisition_date=date(2021, 1, 1),
    )
    db_session.add_all([c_empty, c_dormant])
    db_session.flush()

    # Dormant customer had 2 purchases in early 2021 (cadence = 10.0 days)
    s1 = Sale(
        transaction_number="TXN-DORMANT-01",
        customer_id=c_dormant.id,
        transaction_date=datetime(2021, 1, 1, 12, 0, tzinfo=UTC),
        status="completed",
        subtotal=Decimal("100.00"),
        total_amount=Decimal("100.00"),
    )
    s2 = Sale(
        transaction_number="TXN-DORMANT-02",
        customer_id=c_dormant.id,
        transaction_date=datetime(2021, 1, 11, 12, 0, tzinfo=UTC),
        status="completed",
        subtotal=Decimal("120.00"),
        total_amount=Decimal("120.00"),
    )
    db_session.add_all([s1, s2])
    db_session.commit()

    cutoff = datetime(2023, 1, 1, 12, 0, tzinfo=UTC)
    summary = CustomerCadenceAnalyzer.evaluate(db_session, as_of_date=cutoff)

    rec_empty = next(r for r in summary.records if r.customer_code == "CUST-NO-ORDERS")
    assert rec_empty.eligible_order_count == 0
    assert rec_empty.last_purchase_date is None
    assert rec_empty.days_since_last_purchase is None
    assert rec_empty.cadence_ratio is None
    assert rec_empty.cadence_source == "no_purchases"
    assert rec_empty.risk_tier == CadenceRiskTier.INSUFFICIENT_HISTORY

    rec_dormant = next(r for r in summary.records if r.customer_code == "CUST-DORMANT")
    assert rec_dormant.eligible_order_count == 2
    assert rec_dormant.baseline_cadence_days == 10.0
    assert rec_dormant.days_since_last_purchase == 720.0
    assert rec_dormant.cadence_ratio == 72.0
    assert rec_dormant.risk_tier == CadenceRiskTier.CRITICAL
    assert "critically overdue" in rec_dormant.explanation.summary


def test_explicit_cutoff_behavior_and_future_order_exclusion(db_session: Session):
    """
    Verify that orders occurring after the evaluation cutoff date are strictly excluded.
    """
    c = Customer(
        customer_code="CUST-CUTOFF",
        name="Cutoff Testing Customer",
        email="cutoff@test.com",
        city="Atlanta",
        customer_segment="Retail",
        acquisition_date=date(2023, 1, 1),
    )
    db_session.add(c)
    db_session.flush()

    # 3 orders: Jan 10, Jan 20, and a future order on Dec 10
    s_jan10 = Sale(
        transaction_number="TXN-CUT-01",
        customer_id=c.id,
        transaction_date=datetime(2023, 1, 10, 10, 0, tzinfo=UTC),
        status="completed",
        subtotal=Decimal("100.00"),
        total_amount=Decimal("100.00"),
    )
    s_jan20 = Sale(
        transaction_number="TXN-CUT-02",
        customer_id=c.id,
        transaction_date=datetime(2023, 1, 20, 10, 0, tzinfo=UTC),
        status="completed",
        subtotal=Decimal("100.00"),
        total_amount=Decimal("100.00"),
    )
    s_dec10 = Sale(
        transaction_number="TXN-CUT-FUTURE",
        customer_id=c.id,
        transaction_date=datetime(2023, 12, 10, 10, 0, tzinfo=UTC),
        status="completed",
        subtotal=Decimal("500.00"),
        total_amount=Decimal("500.00"),
    )
    db_session.add_all([s_jan10, s_jan20, s_dec10])
    db_session.commit()

    # Cutoff at Feb 1 (Future Dec order must be excluded)
    cutoff = datetime(2023, 2, 1, 10, 0, tzinfo=UTC)
    summary = CustomerCadenceAnalyzer.evaluate(db_session, as_of_date=cutoff)

    rec = summary.records[0]
    assert rec.eligible_order_count == 2
    assert rec.mean_ipi_days == 10.0
    assert rec.median_ipi_days == 10.0
    assert rec.last_purchase_date == datetime(2023, 1, 20, 10, 0, tzinfo=UTC)
    assert rec.days_since_last_purchase == 12.0
    assert rec.cadence_ratio == 1.2
    assert rec.risk_tier == CadenceRiskTier.LOW


def test_cancelled_and_refunded_transaction_treatment(db_session: Session):
    """
    Verify that cancelled, refunded, and pending transactions are excluded from cadence calculations.
    """
    c = Customer(
        customer_code="CUST-STATUS",
        name="Status Verification Customer",
        email="status@test.com",
        city="Phoenix",
        customer_segment="Corporate",
        acquisition_date=date(2023, 1, 1),
    )
    db_session.add(c)
    db_session.flush()

    # Order 1: Jan 1 (completed)
    # Order 2: Jan 10 (cancelled - excluded)
    # Order 3: Jan 15 (refunded - excluded)
    # Order 4: Jan 20 (pending - excluded)
    # Order 5: Jan 31 (shipped - completed purchase)
    sales = [
        Sale(
            transaction_number="TXN-ST-01",
            customer_id=c.id,
            transaction_date=datetime(2023, 1, 1, 10, 0, tzinfo=UTC),
            status="completed",
            subtotal=Decimal("50.00"),
            total_amount=Decimal("50.00"),
        ),
        Sale(
            transaction_number="TXN-ST-02",
            customer_id=c.id,
            transaction_date=datetime(2023, 1, 10, 10, 0, tzinfo=UTC),
            status="cancelled",
            subtotal=Decimal("50.00"),
            total_amount=Decimal("50.00"),
        ),
        Sale(
            transaction_number="TXN-ST-03",
            customer_id=c.id,
            transaction_date=datetime(2023, 1, 15, 10, 0, tzinfo=UTC),
            status="refunded",
            subtotal=Decimal("50.00"),
            total_amount=Decimal("50.00"),
        ),
        Sale(
            transaction_number="TXN-ST-04",
            customer_id=c.id,
            transaction_date=datetime(2023, 1, 20, 10, 0, tzinfo=UTC),
            status="pending",
            subtotal=Decimal("50.00"),
            total_amount=Decimal("50.00"),
        ),
        Sale(
            transaction_number="TXN-ST-05",
            customer_id=c.id,
            transaction_date=datetime(2023, 1, 31, 10, 0, tzinfo=UTC),
            status="shipped",
            subtotal=Decimal("75.00"),
            total_amount=Decimal("75.00"),
        ),
    ]
    db_session.add_all(sales)
    db_session.commit()

    cutoff = datetime(2023, 2, 10, 10, 0, tzinfo=UTC)
    summary = CustomerCadenceAnalyzer.evaluate(db_session, as_of_date=cutoff)

    rec = summary.records[0]
    assert rec.eligible_order_count == 2
    assert rec.mean_ipi_days == 30.0  # Jan 1 to Jan 31
    assert rec.median_ipi_days == 30.0
    assert rec.last_purchase_date == datetime(2023, 1, 31, 10, 0, tzinfo=UTC)
    assert rec.days_since_last_purchase == 10.0
    assert rec.cadence_ratio == pytest.approx(10.0 / 30.0, 0.0001)
    assert rec.risk_tier == CadenceRiskTier.LOW


def test_tenant_isolation_multitenancy(db_session: Session):
    """
    Verify strict tenant isolation: business_id scopes customers and sales.
    Cross-tenant records are never exposed or mixed into calculations.
    """
    # Tenant 1
    c_t1 = Customer(
        customer_code="CUST-T1",
        business_id="biz-tenant-01",
        name="Tenant 1 Buyer",
        email="t1@corp.com",
        city="Seattle",
        customer_segment="Corporate",
        acquisition_date=date(2023, 1, 1),
    )
    # Tenant 2
    c_t2 = Customer(
        customer_code="CUST-T2",
        business_id="biz-tenant-02",
        name="Tenant 2 Buyer",
        email="t2@corp.com",
        city="Portland",
        customer_segment="Corporate",
        acquisition_date=date(2023, 1, 1),
    )
    db_session.add_all([c_t1, c_t2])
    db_session.flush()

    # Sales for Tenant 1
    s_t1_1 = Sale(
        transaction_number="TXN-T1-01",
        business_id="biz-tenant-01",
        customer_id=c_t1.id,
        transaction_date=datetime(2023, 1, 1, 10, 0, tzinfo=UTC),
        status="completed",
        subtotal=Decimal("100.00"),
        total_amount=Decimal("100.00"),
    )
    s_t1_2 = Sale(
        transaction_number="TXN-T1-02",
        business_id="biz-tenant-01",
        customer_id=c_t1.id,
        transaction_date=datetime(2023, 1, 21, 10, 0, tzinfo=UTC),
        status="completed",
        subtotal=Decimal("100.00"),
        total_amount=Decimal("100.00"),
    )

    # Sales for Tenant 2
    s_t2_1 = Sale(
        transaction_number="TXN-T2-01",
        business_id="biz-tenant-02",
        customer_id=c_t2.id,
        transaction_date=datetime(2023, 1, 5, 10, 0, tzinfo=UTC),
        status="completed",
        subtotal=Decimal("100.00"),
        total_amount=Decimal("100.00"),
    )

    # Cross-tenant intrusion row: Sale tagged with biz-tenant-02 but pointing to c_t1.id
    s_intruder = Sale(
        transaction_number="TXN-INTRUDER",
        business_id="biz-tenant-02",
        customer_id=c_t1.id,
        transaction_date=datetime(2023, 1, 11, 10, 0, tzinfo=UTC),
        status="completed",
        subtotal=Decimal("999.00"),
        total_amount=Decimal("999.00"),
    )

    db_session.add_all([s_t1_1, s_t1_2, s_t2_1, s_intruder])
    db_session.commit()

    # Query strictly scoped to biz-tenant-01
    ctx1 = AnalysisContext(business_id="biz-tenant-01")
    cutoff = datetime(2023, 2, 1, 10, 0, tzinfo=UTC)
    summary1 = CustomerCadenceAnalyzer.evaluate(db_session, context=ctx1, as_of_date=cutoff)

    assert summary1.total_customers_evaluated == 1
    assert summary1.business_id == "biz-tenant-01"
    rec1 = summary1.records[0]
    assert rec1.customer_code == "CUST-T1"
    # Must only see the 2 sales belonging to biz-tenant-01; intruder sale is ignored
    assert rec1.eligible_order_count == 2
    assert rec1.mean_ipi_days == 20.0
    assert rec1.baseline_cadence_days == 20.0

    # Query strictly scoped to biz-tenant-02
    ctx2 = AnalysisContext(business_id="biz-tenant-02")
    summary2 = CustomerCadenceAnalyzer.evaluate(db_session, context=ctx2, as_of_date=cutoff)

    assert summary2.total_customers_evaluated == 1
    assert summary2.business_id == "biz-tenant-02"
    rec2 = summary2.records[0]
    assert rec2.customer_code == "CUST-T2"
    assert rec2.eligible_order_count == 1


def test_deterministic_output_and_stable_risk_tier_boundaries(db_session: Session):
    """
    Verify exact risk tier boundary transitions:
      ratio < 1.25 -> LOW
      1.25 <= ratio < 2.0 -> MEDIUM
      2.0 <= ratio < 3.0 -> HIGH
      ratio >= 3.0 -> CRITICAL
    """
    c = Customer(
        customer_code="CUST-BOUNDARIES",
        name="Boundary Tester",
        email="bounds@test.com",
        city="San Jose",
        customer_segment="Retail",
        acquisition_date=date(2023, 1, 1),
    )
    db_session.add(c)
    db_session.flush()

    # 2 orders 10.0 days apart: cadence = 10.0 days
    s1 = Sale(
        transaction_number="TXN-BND-01",
        customer_id=c.id,
        transaction_date=datetime(2023, 1, 1, 0, 0, tzinfo=UTC),
        status="completed",
        subtotal=Decimal("50.00"),
        total_amount=Decimal("50.00"),
    )
    s2 = Sale(
        transaction_number="TXN-BND-02",
        customer_id=c.id,
        transaction_date=datetime(2023, 1, 11, 0, 0, tzinfo=UTC),
        status="completed",
        subtotal=Decimal("50.00"),
        total_amount=Decimal("50.00"),
    )
    db_session.add_all([s1, s2])
    db_session.commit()

    test_cases = [
        # (elapsed_days, expected_ratio, expected_tier)
        (5.0, 0.5, CadenceRiskTier.LOW),
        (12.4, 1.24, CadenceRiskTier.LOW),
        (12.5, 1.25, CadenceRiskTier.MEDIUM),
        (19.9, 1.99, CadenceRiskTier.MEDIUM),
        (20.0, 2.0, CadenceRiskTier.HIGH),
        (29.9, 2.99, CadenceRiskTier.HIGH),
        (30.0, 3.0, CadenceRiskTier.CRITICAL),
        (50.0, 5.0, CadenceRiskTier.CRITICAL),
    ]

    for elapsed, exp_ratio, exp_tier in test_cases:
        cutoff_dt = datetime(2023, 1, 11, 0, 0, tzinfo=UTC) + timedelta(days=elapsed)
        res = CustomerCadenceAnalyzer.evaluate(db_session, as_of_date=cutoff_dt)
        r = res.records[0]
        assert r.cadence_ratio == pytest.approx(exp_ratio, abs=0.001)
        assert r.risk_tier == exp_tier, (
            f"Failed for elapsed={elapsed}, expected {exp_tier}, got {r.risk_tier}"
        )


def test_segment_fallback_behavior(db_session: Session):
    """
    Verify segment fallback logic:
    - 3 repeat Wholesale customers establish segment median cadence.
    - 1 one-time Wholesale customer receives segment fallback score.
    - Segment fallback is suppressed when disabled or population is insufficient.
    """
    # 3 repeat Wholesale customers (cadence = 30.0 days each)
    wholesale_repeat = []
    for i in range(1, 4):
        c = Customer(
            customer_code=f"CUST-WS-REP-{i}",
            name=f"Wholesale Repeat {i}",
            email=f"wsrep{i}@corp.com",
            city="Boston",
            customer_segment="Wholesale",
            acquisition_date=date(2023, 1, 1),
        )
        db_session.add(c)
        wholesale_repeat.append(c)
    db_session.flush()

    for idx, c in enumerate(wholesale_repeat):
        s0 = Sale(
            transaction_number=f"TXN-WS-REP-{idx}-0",
            customer_id=c.id,
            transaction_date=datetime(2022, 12, 2, 10, 0, tzinfo=UTC),
            status="completed",
            subtotal=Decimal("200.00"),
            total_amount=Decimal("200.00"),
        )
        s1 = Sale(
            transaction_number=f"TXN-WS-REP-{idx}-1",
            customer_id=c.id,
            transaction_date=datetime(2023, 1, 1, 10, 0, tzinfo=UTC),
            status="completed",
            subtotal=Decimal("200.00"),
            total_amount=Decimal("200.00"),
        )
        s2 = Sale(
            transaction_number=f"TXN-WS-REP-{idx}-2",
            customer_id=c.id,
            transaction_date=datetime(2023, 1, 31, 10, 0, tzinfo=UTC),
            status="completed",
            subtotal=Decimal("200.00"),
            total_amount=Decimal("200.00"),
        )
        db_session.add_all([s0, s1, s2])

    # 1 repeat Wholesale customer needing fallback (has 2 orders, but min_orders_for_individual_cadence=3)
    c_rep_fallback = Customer(
        customer_code="CUST-WS-REP-FALLBACK",
        name="Wholesale Repeat Needing Fallback",
        email="wsfallback@corp.com",
        city="Boston",
        customer_segment="Wholesale",
        acquisition_date=date(2023, 1, 1),
    )
    # 1 one-time Wholesale customer
    c_single = Customer(
        customer_code="CUST-WS-SINGLE",
        name="Wholesale Single Buyer",
        email="wssingle@corp.com",
        city="Boston",
        customer_segment="Wholesale",
        acquisition_date=date(2023, 1, 1),
    )
    db_session.add_all([c_rep_fallback, c_single])
    db_session.flush()

    s_rf1 = Sale(
        transaction_number="TXN-WS-RF-1",
        customer_id=c_rep_fallback.id,
        transaction_date=datetime(2023, 1, 1, 10, 0, tzinfo=UTC),
        status="completed",
        subtotal=Decimal("150.00"),
        total_amount=Decimal("150.00"),
    )
    s_rf2 = Sale(
        transaction_number="TXN-WS-RF-2",
        customer_id=c_rep_fallback.id,
        transaction_date=datetime(2023, 1, 16, 10, 0, tzinfo=UTC),
        status="completed",
        subtotal=Decimal("150.00"),
        total_amount=Decimal("150.00"),
    )
    s_single = Sale(
        transaction_number="TXN-WS-SINGLE-1",
        customer_id=c_single.id,
        transaction_date=datetime(2023, 1, 1, 10, 0, tzinfo=UTC),
        status="completed",
        subtotal=Decimal("300.00"),
        total_amount=Decimal("300.00"),
    )
    db_session.add_all([s_rf1, s_rf2, s_single])
    db_session.commit()

    cutoff = datetime(2023, 2, 15, 10, 0, tzinfo=UTC)

    # Case 1: Fallback enabled for eligible repeat customers (min_orders_for_individual_cadence=3, use_segment_fallback=True)
    cfg_fb = CadenceConfig(min_orders_for_individual_cadence=3, use_segment_fallback=True)
    res1 = CustomerCadenceAnalyzer.evaluate(db_session, as_of_date=cutoff, config=cfg_fb)

    assert res1.segment_baselines.get("Wholesale") == 30.0
    assert res1.segment_fallbacks_used == 1

    # Eligible repeat buyer receives segment fallback
    rec_rf = next(r for r in res1.records if r.customer_code == "CUST-WS-REP-FALLBACK")
    assert rec_rf.is_repeat_buyer is True
    assert rec_rf.cadence_source == "segment_fallback"
    assert rec_rf.baseline_cadence_days == 30.0
    assert rec_rf.days_since_last_purchase == 30.0
    assert rec_rf.cadence_ratio == 1.0
    assert rec_rf.risk_tier == CadenceRiskTier.LOW

    # One-time buyer is protected: NEVER receives segment fallback, always INSUFFICIENT_HISTORY
    rec_single1 = next(r for r in res1.records if r.customer_code == "CUST-WS-SINGLE")
    assert rec_single1.is_repeat_buyer is False
    assert rec_single1.cadence_source == "insufficient_history"
    assert rec_single1.baseline_cadence_days is None
    assert rec_single1.cadence_ratio is None
    assert rec_single1.risk_tier == CadenceRiskTier.INSUFFICIENT_HISTORY

    # Case 2: Fallback disabled in config
    cfg_disabled = CadenceConfig(min_orders_for_individual_cadence=3, use_segment_fallback=False)
    res2 = CustomerCadenceAnalyzer.evaluate(db_session, as_of_date=cutoff, config=cfg_disabled)
    rec_rf2 = next(r for r in res2.records if r.customer_code == "CUST-WS-REP-FALLBACK")
    assert rec_rf2.cadence_source == "insufficient_history"
    assert rec_rf2.risk_tier == CadenceRiskTier.INSUFFICIENT_HISTORY

    rec_single2 = next(r for r in res2.records if r.customer_code == "CUST-WS-SINGLE")
    assert rec_single2.cadence_source == "insufficient_history"
    assert rec_single2.risk_tier == CadenceRiskTier.INSUFFICIENT_HISTORY

    # Case 3: min_segment_customers=5 (only 3 exist -> evidence insufficient)
    cfg_high_min = CadenceConfig(min_orders_for_individual_cadence=3, use_segment_fallback=True, min_segment_customers=5)
    res3 = CustomerCadenceAnalyzer.evaluate(db_session, as_of_date=cutoff, config=cfg_high_min)
    assert res3.segment_baselines.get("Wholesale") is None
    rec_rf3 = next(r for r in res3.records if r.customer_code == "CUST-WS-REP-FALLBACK")
    assert rec_rf3.cadence_source == "insufficient_history"
    assert rec_rf3.risk_tier == CadenceRiskTier.INSUFFICIENT_HISTORY


def test_multi_period_db_integration(multi_period_db: Session):
    """
    Verify cadence evaluation on existing standard multi_period_db fixture.
    CUST-001 (Corporate): 3 completed sales (May 10, June 5, June 20).
    CUST-002 (Retail): 1 completed sale (May 20).
    """
    cutoff = datetime(2023, 7, 1, 0, 0, tzinfo=UTC)
    summary = CustomerCadenceAnalyzer.evaluate(multi_period_db, as_of_date=cutoff)

    assert summary.total_customers_evaluated == 2
    rec1 = next(r for r in summary.records if r.customer_code == "CUST-001")
    assert rec1.eligible_order_count == 3
    assert rec1.cadence_source == "individual"
    assert rec1.mean_ipi_days > 0.0
    assert rec1.median_ipi_days > 0.0
    assert rec1.std_ipi_days is not None
    assert rec1.risk_tier == CadenceRiskTier.LOW

    rec2 = next(r for r in summary.records if r.customer_code == "CUST-002")
    assert rec2.eligible_order_count == 1
    # Only 1 retail customer in DB, so segment evidence threshold (min 3) is not met -> insufficient history
    assert rec2.risk_tier == CadenceRiskTier.INSUFFICIENT_HISTORY
    assert rec2.cadence_source == "insufficient_history"


def test_future_acquired_customers_excluded_from_historical_cutoff(db_session: Session):
    """
    Verify that customers acquired after the historical cutoff date are excluded
    from the evaluated population to prevent cohort size distortion and temporal leakage.
    """
    c_past = Customer(
        customer_code="CUST-ACQ-PAST",
        name="Existing Customer",
        email="past@acq.com",
        city="Denver",
        customer_segment="Retail",
        acquisition_date=date(2022, 6, 1),
    )
    c_future = Customer(
        customer_code="CUST-ACQ-FUTURE",
        name="Future Acquired Customer",
        email="future@acq.com",
        city="Denver",
        customer_segment="Retail",
        acquisition_date=date(2023, 6, 1),
    )
    db_session.add_all([c_past, c_future])
    db_session.flush()

    s = Sale(
        transaction_number="TXN-PAST-01",
        customer_id=c_past.id,
        transaction_date=datetime(2022, 10, 1, 10, 0, tzinfo=UTC),
        status="completed",
        subtotal=Decimal("50.00"),
        total_amount=Decimal("50.00"),
    )
    db_session.add(s)
    db_session.commit()

    # Historical cutoff at 2023-01-01 (c_future did not exist yet)
    cutoff = datetime(2023, 1, 1, 0, 0, tzinfo=UTC)
    summary = CustomerCadenceAnalyzer.evaluate(db_session, as_of_date=cutoff)

    assert summary.total_customers_evaluated == 1
    assert summary.records[0].customer_code == "CUST-ACQ-PAST"
    assert not any(r.customer_code == "CUST-ACQ-FUTURE" for r in summary.records)


def test_date_cutoff_includes_entire_calendar_day(db_session: Session):
    """
    Verify that passing as_of_date as a calendar date includes all transactions
    occurring on that date up to 23:59:59 UTC.
    """
    c = Customer(
        customer_code="CUST-EOD",
        name="End Of Day Customer",
        email="eod@test.com",
        city="Phoenix",
        customer_segment="Retail",
        acquisition_date=date(2023, 1, 1),
    )
    db_session.add(c)
    db_session.flush()

    # Order occurs at 18:30 on March 15
    s1 = Sale(
        transaction_number="TXN-EOD-01",
        customer_id=c.id,
        transaction_date=datetime(2023, 3, 15, 18, 30, tzinfo=UTC),
        status="completed",
        subtotal=Decimal("50.00"),
        total_amount=Decimal("50.00"),
    )
    # Order occurs on March 16 (next day)
    s2 = Sale(
        transaction_number="TXN-EOD-02",
        customer_id=c.id,
        transaction_date=datetime(2023, 3, 16, 9, 0, tzinfo=UTC),
        status="completed",
        subtotal=Decimal("50.00"),
        total_amount=Decimal("50.00"),
    )
    db_session.add_all([s1, s2])
    db_session.commit()

    # Cutoff specified as date(2023, 3, 15)
    summary = CustomerCadenceAnalyzer.evaluate(db_session, as_of_date=date(2023, 3, 15))

    assert summary.total_customers_evaluated == 1
    rec = summary.records[0]
    # The March 15 18:30 order is included; the March 16 order is excluded
    assert rec.eligible_order_count == 1
    assert rec.last_purchase_date == datetime(2023, 3, 15, 18, 30, tzinfo=UTC)


def test_single_customer_id_filter_utilizes_tenant_segment_baseline(db_session: Session):
    """
    Verify that filtering by customer_ids to score a single one-time buyer
    successfully looks up the segment baseline from the authorized tenant business.
    """
    biz_id = "biz-single-filter"

    # 3 repeat Wholesale customers belonging to biz_id (cadence = 20.0 days each)
    repeat_custs = []
    for i in range(1, 4):
        c = Customer(
            customer_code=f"CUST-FILTER-REP-{i}",
            business_id=biz_id,
            name=f"Filter Repeat {i}",
            email=f"filter_rep{i}@corp.com",
            city="Boston",
            customer_segment="Wholesale",
            acquisition_date=date(2023, 1, 1),
        )
        db_session.add(c)
        repeat_custs.append(c)
    db_session.flush()

    for idx, c in enumerate(repeat_custs):
        s0 = Sale(
            transaction_number=f"TXN-FILTER-REP-{idx}-0",
            business_id=biz_id,
            customer_id=c.id,
            transaction_date=datetime(2022, 12, 12, 10, 0, tzinfo=UTC),
            status="completed",
            subtotal=Decimal("100.00"),
            total_amount=Decimal("100.00"),
        )
        s1 = Sale(
            transaction_number=f"TXN-FILTER-REP-{idx}-1",
            business_id=biz_id,
            customer_id=c.id,
            transaction_date=datetime(2023, 1, 1, 10, 0, tzinfo=UTC),
            status="completed",
            subtotal=Decimal("100.00"),
            total_amount=Decimal("100.00"),
        )
        s2 = Sale(
            transaction_number=f"TXN-FILTER-REP-{idx}-2",
            business_id=biz_id,
            customer_id=c.id,
            transaction_date=datetime(2023, 1, 21, 10, 0, tzinfo=UTC),
            status="completed",
            subtotal=Decimal("100.00"),
            total_amount=Decimal("100.00"),
        )
        db_session.add_all([s0, s1, s2])

    # 1 repeat Wholesale customer needing fallback (has 2 orders, config requires 3)
    c_target = Customer(
        customer_code="CUST-FILTER-TARGET",
        business_id=biz_id,
        name="Filter Target Buyer",
        email="filter_target@corp.com",
        city="Boston",
        customer_segment="Wholesale",
        acquisition_date=date(2023, 1, 1),
    )
    # 1 one-time buyer to verify isolation from fallback
    c_single = Customer(
        customer_code="CUST-FILTER-ONE-TIME",
        business_id=biz_id,
        name="Filter One Time Buyer",
        email="filter_single@corp.com",
        city="Boston",
        customer_segment="Wholesale",
        acquisition_date=date(2023, 1, 1),
    )
    db_session.add_all([c_target, c_single])
    db_session.flush()

    s_target1 = Sale(
        transaction_number="TXN-FILTER-TARGET-1",
        business_id=biz_id,
        customer_id=c_target.id,
        transaction_date=datetime(2023, 1, 1, 10, 0, tzinfo=UTC),
        status="completed",
        subtotal=Decimal("150.00"),
        total_amount=Decimal("150.00"),
    )
    s_target2 = Sale(
        transaction_number="TXN-FILTER-TARGET-2",
        business_id=biz_id,
        customer_id=c_target.id,
        transaction_date=datetime(2023, 1, 16, 10, 0, tzinfo=UTC),
        status="completed",
        subtotal=Decimal("150.00"),
        total_amount=Decimal("150.00"),
    )
    s_single = Sale(
        transaction_number="TXN-FILTER-SINGLE-1",
        business_id=biz_id,
        customer_id=c_single.id,
        transaction_date=datetime(2023, 1, 1, 10, 0, tzinfo=UTC),
        status="completed",
        subtotal=Decimal("100.00"),
        total_amount=Decimal("100.00"),
    )
    db_session.add_all([s_target1, s_target2, s_single])
    db_session.commit()

    # Query filtered specifically to c_target.id with fallback enabled
    cfg = CadenceConfig(min_orders_for_individual_cadence=3, use_segment_fallback=True)
    ctx = AnalysisContext(business_id=biz_id, customer_ids=[c_target.id])
    cutoff = datetime(2023, 1, 31, 10, 0, tzinfo=UTC)
    summary = CustomerCadenceAnalyzer.evaluate(db_session, context=ctx, as_of_date=cutoff, config=cfg)

    assert summary.total_customers_evaluated == 1
    rec = summary.records[0]
    assert rec.customer_code == "CUST-FILTER-TARGET"
    assert rec.eligible_order_count == 2
    assert rec.is_repeat_buyer is True
    # Segment baseline of 20.0 days was resolved from the tenant's repeat population!
    assert rec.cadence_source == "segment_fallback"
    assert rec.baseline_cadence_days == 20.0
    assert rec.days_since_last_purchase == 15.0
    assert rec.cadence_ratio == 0.75
    assert rec.risk_tier == CadenceRiskTier.LOW

    # Query filtered to one-time customer: must receive INSUFFICIENT_HISTORY even with fallback enabled
    ctx_single = AnalysisContext(business_id=biz_id, customer_ids=[c_single.id])
    summary_single = CustomerCadenceAnalyzer.evaluate(db_session, context=ctx_single, as_of_date=cutoff, config=cfg)
    rec_s = summary_single.records[0]
    assert rec_s.customer_code == "CUST-FILTER-ONE-TIME"
    assert rec_s.eligible_order_count == 1
    assert rec_s.is_repeat_buyer is False
    assert rec_s.risk_tier == CadenceRiskTier.INSUFFICIENT_HISTORY
    assert rec_s.cadence_source == "insufficient_history"


def test_cadence_config_validates_thresholds_and_statistic():
    """
    Verify CadenceConfig pydantic validation:
    - Enforces low_threshold < medium_threshold < high_threshold.
    - Enforces cadence_statistic in ('median', 'mean').
    """
    # Valid config works
    cfg = CadenceConfig(low_threshold=1.1, medium_threshold=2.2, high_threshold=3.3)
    assert cfg.low_threshold == 1.1

    # Inverted thresholds rejected
    with pytest.raises(ValidationError):
        CadenceConfig(low_threshold=3.0, medium_threshold=2.0, high_threshold=1.0)

    # Equal thresholds rejected
    with pytest.raises(ValidationError):
        CadenceConfig(low_threshold=1.5, medium_threshold=1.5, high_threshold=2.0)

    # Invalid cadence statistic rejected
    with pytest.raises(ValidationError):
        CadenceConfig(cadence_statistic="geometric_mean")  # type: ignore[arg-type]


def test_multiple_sale_items_do_not_duplicate_order_intervals(db_session: Session):
    """
    Verify that an order containing multiple line items counts as a single order
    and does not duplicate interval observations.
    """
    c = Customer(
        customer_code="CUST-ITEMS",
        name="Multi Line Item Customer",
        email="items@test.com",
        city="Atlanta",
        customer_segment="Corporate",
        acquisition_date=date(2023, 1, 1),
    )
    p1 = Product(
        sku="SKU-CAD-1",
        name="Product 1",
        category="Cat A",
        subcategory="Subcat A",
        unit_cost=Decimal("10.00"),
        selling_price=Decimal("20.00"),
    )
    p2 = Product(
        sku="SKU-CAD-2",
        name="Product 2",
        category="Cat B",
        subcategory="Subcat B",
        unit_cost=Decimal("15.00"),
        selling_price=Decimal("30.00"),
    )
    db_session.add_all([c, p1, p2])
    db_session.flush()

    # Order 1: Jan 1 with 2 line items
    s1 = Sale(
        transaction_number="TXN-MULTI-01",
        customer_id=c.id,
        transaction_date=datetime(2023, 1, 1, 10, 0, tzinfo=UTC),
        status="completed",
        subtotal=Decimal("70.00"),
        total_amount=Decimal("70.00"),
    )
    db_session.add(s1)
    db_session.flush()
    i1_1 = SaleItem(
        sale_id=s1.id,
        product_id=p1.id,
        quantity=2,
        unit_price=Decimal("20.00"),
        line_total=Decimal("40.00"),
    )
    i1_2 = SaleItem(
        sale_id=s1.id,
        product_id=p2.id,
        quantity=1,
        unit_price=Decimal("30.00"),
        line_total=Decimal("30.00"),
    )
    db_session.add_all([i1_1, i1_2])

    # Order 2: Jan 11 with 1 line item
    s2 = Sale(
        transaction_number="TXN-MULTI-02",
        customer_id=c.id,
        transaction_date=datetime(2023, 1, 11, 10, 0, tzinfo=UTC),
        status="completed",
        subtotal=Decimal("20.00"),
        total_amount=Decimal("20.00"),
    )
    db_session.add(s2)
    db_session.flush()
    i2_1 = SaleItem(
        sale_id=s2.id,
        product_id=p1.id,
        quantity=1,
        unit_price=Decimal("20.00"),
        line_total=Decimal("20.00"),
    )
    db_session.add(i2_1)
    db_session.commit()

    cutoff = datetime(2023, 1, 21, 10, 0, tzinfo=UTC)
    summary = CustomerCadenceAnalyzer.evaluate(db_session, as_of_date=cutoff)

    assert summary.total_customers_evaluated == 1
    rec = summary.records[0]
    # Must count exactly 2 distinct orders despite 3 line items
    assert rec.eligible_order_count == 2
    assert rec.mean_ipi_days == 10.0
    assert rec.median_ipi_days == 10.0
    assert rec.days_since_last_purchase == 10.0
    assert rec.cadence_ratio == 1.0


def test_one_time_buyer_high_recency_never_classified_as_high_or_critical(db_session: Session):
    """
    Verify Rule 1 & Rule 3:
    A one-time buyer with very high elapsed recency (e.g. 400 days) must NEVER receive
    HIGH or CRITICAL churn risk, even if segment fallback is enabled with a short segment cadence (e.g. 20 days).
    """
    # Create segment with established 20-day cadence
    for i in range(1, 4):
        c_rep = Customer(
            customer_code=f"CUST-HR-REP-{i}",
            name=f"HR Repeat {i}",
            email=f"hrrep{i}@test.com",
            city="Seattle",
            customer_segment="Enterprise",
            acquisition_date=date(2022, 1, 1),
        )
        db_session.add(c_rep)
        db_session.flush()
        s1 = Sale(
            transaction_number=f"TXN-HR-REP-{i}-1",
            customer_id=c_rep.id,
            transaction_date=datetime(2022, 1, 1, 10, 0, tzinfo=UTC),
            status="completed",
            subtotal=Decimal("100.00"),
            total_amount=Decimal("100.00"),
        )
        s2 = Sale(
            transaction_number=f"TXN-HR-REP-{i}-2",
            customer_id=c_rep.id,
            transaction_date=datetime(2022, 1, 21, 10, 0, tzinfo=UTC),
            status="completed",
            subtotal=Decimal("100.00"),
            total_amount=Decimal("100.00"),
        )
        db_session.add_all([s1, s2])

    # One-time buyer who purchased 400 days ago
    c_dormant = Customer(
        customer_code="CUST-DORMANT-ONE-TIME",
        name="Dormant One Time Buyer",
        email="dormant@test.com",
        city="Seattle",
        customer_segment="Enterprise",
        acquisition_date=date(2022, 1, 1),
    )
    db_session.add(c_dormant)
    db_session.flush()
    s_dormant = Sale(
        transaction_number="TXN-DORMANT-01",
        customer_id=c_dormant.id,
        transaction_date=datetime(2022, 1, 1, 10, 0, tzinfo=UTC),
        status="completed",
        subtotal=Decimal("50.00"),
        total_amount=Decimal("50.00"),
    )
    db_session.add(s_dormant)
    db_session.commit()

    # Cutoff at Feb 5, 2023 (400 days after purchase) with segment fallback explicitly enabled
    cutoff = datetime(2023, 2, 5, 10, 0, tzinfo=UTC)
    cfg_fb = CadenceConfig(use_segment_fallback=True)
    summary = CustomerCadenceAnalyzer.evaluate(db_session, as_of_date=cutoff, config=cfg_fb)

    rec = next(r for r in summary.records if r.customer_code == "CUST-DORMANT-ONE-TIME")
    assert rec.eligible_order_count == 1
    assert rec.is_repeat_buyer is False
    assert rec.days_since_last_purchase == 400.0
    # Even though recency / segment_cadence would be 400 / 20 = 20.0x,
    # the customer MUST NOT be classified as CRITICAL or HIGH!
    assert rec.baseline_cadence_days is None
    assert rec.cadence_ratio is None
    assert rec.risk_tier == CadenceRiskTier.INSUFFICIENT_HISTORY
    assert rec.risk_tier not in (CadenceRiskTier.HIGH, CadenceRiskTier.CRITICAL, CadenceRiskTier.LOW, CadenceRiskTier.MEDIUM)
    assert "insufficient repeat purchase history to estimate personal cadence" in rec.explanation.summary


def test_two_distinct_eligible_purchase_events_cadence_policy(db_session: Session):
    """
    Verify Rule 1 & Rule 5:
    A customer with two distinct eligible completed purchase events separated in time
    is recognized as an eligible repeat buyer and scored according to personal cadence.
    """
    c = Customer(
        customer_code="CUST-TWO-DISTINCT",
        name="Two Distinct Purchases Buyer",
        email="twodistinct@test.com",
        city="Denver",
        customer_segment="Retail",
        acquisition_date=date(2023, 1, 1),
    )
    db_session.add(c)
    db_session.flush()

    s1 = Sale(
        transaction_number="TXN-DIST-01",
        customer_id=c.id,
        transaction_date=datetime(2023, 1, 1, 10, 0, tzinfo=UTC),
        status="completed",
        subtotal=Decimal("50.00"),
        total_amount=Decimal("50.00"),
    )
    s2 = Sale(
        transaction_number="TXN-DIST-02",
        customer_id=c.id,
        transaction_date=datetime(2023, 1, 21, 10, 0, tzinfo=UTC),
        status="completed",
        subtotal=Decimal("50.00"),
        total_amount=Decimal("50.00"),
    )
    db_session.add_all([s1, s2])
    db_session.commit()

    # Cutoff at Jan 31 (10 days after second purchase; interval = 20 days -> ratio = 0.5x)
    cutoff = datetime(2023, 1, 31, 10, 0, tzinfo=UTC)
    summary = CustomerCadenceAnalyzer.evaluate(db_session, as_of_date=cutoff)

    rec = summary.records[0]
    assert rec.eligible_order_count == 2
    assert rec.distinct_purchase_dates_count == 2
    assert rec.is_repeat_buyer is True
    assert rec.mean_ipi_days == 20.0
    assert rec.median_ipi_days == 20.0
    assert rec.baseline_cadence_days == 20.0
    assert rec.cadence_source == "individual"
    assert rec.days_since_last_purchase == 10.0
    assert rec.cadence_ratio == 0.5
    assert rec.risk_tier == CadenceRiskTier.LOW


def test_one_time_buyer_safety_invariant_under_segment_fallback_toggle(db_session: Session):
    """
    Verify that whether use_segment_fallback is True or False, a one-time buyer
    invariantly receives INSUFFICIENT_HISTORY and is never scored as overdue.
    """
    c = Customer(
        customer_code="CUST-TOGGLE-SINGLE",
        name="Toggle Test Single Buyer",
        email="toggle@test.com",
        city="Austin",
        customer_segment="Retail",
        acquisition_date=date(2023, 1, 1),
    )
    db_session.add(c)
    db_session.flush()

    s = Sale(
        transaction_number="TXN-TOGGLE-01",
        customer_id=c.id,
        transaction_date=datetime(2023, 1, 1, 10, 0, tzinfo=UTC),
        status="completed",
        subtotal=Decimal("100.00"),
        total_amount=Decimal("100.00"),
    )
    db_session.add(s)
    db_session.commit()

    cutoff = datetime(2023, 6, 1, 10, 0, tzinfo=UTC)

    # Test with fallback=False
    res_false = CustomerCadenceAnalyzer.evaluate(
        db_session, as_of_date=cutoff, config=CadenceConfig(use_segment_fallback=False)
    )
    rec_false = res_false.records[0]
    assert rec_false.risk_tier == CadenceRiskTier.INSUFFICIENT_HISTORY
    assert rec_false.cadence_ratio is None
    assert rec_false.is_repeat_buyer is False

    # Test with fallback=True
    res_true = CustomerCadenceAnalyzer.evaluate(
        db_session, as_of_date=cutoff, config=CadenceConfig(use_segment_fallback=True)
    )
    rec_true = res_true.records[0]
    assert rec_true.risk_tier == CadenceRiskTier.INSUFFICIENT_HISTORY
    assert rec_true.cadence_ratio is None
    assert rec_true.is_repeat_buyer is False


def test_genuinely_overdue_repeat_buyer_elevated_risk(db_session: Session):
    """
    Verify that a customer with an established repeat pattern who is genuinely overdue
    is correctly classified as elevated risk (HIGH or CRITICAL).
    """
    c = Customer(
        customer_code="CUST-OVERDUE-REP",
        name="Overdue Repeat Buyer",
        email="overdue@test.com",
        city="Chicago",
        customer_segment="Retail",
        acquisition_date=date(2023, 1, 1),
    )
    db_session.add(c)
    db_session.flush()

    # 3 orders with an established 10-day cadence (Jan 1, Jan 11, Jan 21)
    dates = [
        datetime(2023, 1, 1, 10, 0, tzinfo=UTC),
        datetime(2023, 1, 11, 10, 0, tzinfo=UTC),
        datetime(2023, 1, 21, 10, 0, tzinfo=UTC),
    ]
    sales = [
        Sale(
            transaction_number=f"TXN-OVD-{i + 1}",
            customer_id=c.id,
            transaction_date=d,
            status="completed",
            subtotal=Decimal("50.00"),
            total_amount=Decimal("50.00"),
        )
        for i, d in enumerate(dates)
    ]
    db_session.add_all(sales)
    db_session.commit()

    # Cutoff at Feb 25 (35 days after last purchase; cadence = 10.0 days -> ratio = 3.5x >= 3.0x -> CRITICAL)
    cutoff = datetime(2023, 2, 25, 10, 0, tzinfo=UTC)
    summary = CustomerCadenceAnalyzer.evaluate(db_session, as_of_date=cutoff)

    rec = summary.records[0]
    assert rec.eligible_order_count == 3
    assert rec.is_repeat_buyer is True
    assert rec.baseline_cadence_days == 10.0
    assert rec.cadence_source == "individual"
    assert rec.days_since_last_purchase == 35.0
    assert rec.cadence_ratio == 3.5
    assert rec.risk_tier == CadenceRiskTier.CRITICAL
    assert "critically overdue" in rec.explanation.summary
