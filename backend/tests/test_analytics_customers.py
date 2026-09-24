"""Tests for customer RFM segmentation, cohort retention, and repeat-purchase metrics."""

from datetime import datetime, timezone
from decimal import Decimal
import pytest
from sqlalchemy.orm import Session
from app.analytics.core.context import AnalysisContext
from app.analytics.customer.rfm import RFMAnalyzer
from app.analytics.customer.cohorts import CustomerCohortAnalyzer
from app.analytics.customer.repeat_purchase import RepeatPurchaseAnalyzer
from backend.tests.test_analytics_financial import multi_period_db


def test_repeat_purchase_metrics(multi_period_db: Session):
    """Verify one-time vs repeat purchase rate calculations."""
    # Across both May and June:
    # Customer 1 (CUST-001) placed TXN-202305-01, TXN-202306-01, TXN-202306-02 (3 orders) -> repeat customer
    # Customer 2 (CUST-002) placed TXN-202305-02 (1 order) -> one-time customer
    res = RepeatPurchaseAnalyzer.evaluate(multi_period_db)

    assert res.total_customers_with_orders == 2
    assert res.repeat_customers == 1
    assert res.one_time_customers == 1
    assert res.repeat_purchase_rate == 50.0
    assert res.average_orders_per_customer == 2.0
    assert res.orders_distribution["1"] == 1
    assert res.orders_distribution["3-5"] == 1


def test_rfm_analysis(multi_period_db: Session):
    """Verify RFM calculation and scoring."""
    ref_date = datetime(2023, 7, 1, tzinfo=timezone.utc)
    summary = RFMAnalyzer.evaluate(
        multi_period_db, as_of_date=ref_date, quantile_bins=3, limit_top=10
    )

    assert summary.total_customers_analyzed == 2
    # CUST-001 has higher monetary and frequency, and more recent purchase (June 20 vs May 20)
    top = summary.top_customers[0]
    assert top.customer_code == "CUST-001"
    assert top.frequency_orders == 3
    # Net spend CUST-001 = 65.00 (Sale 1) + 140.00 (Sale 3) + 200.00 (Sale 4) = 405.00
    assert top.monetary_revenue == Decimal("405.00")
    assert top.r_score >= 1
    assert top.f_score >= 1


def test_cohort_retention(multi_period_db: Session):
    """Verify monthly acquisition cohort analysis."""
    # C1 acquired 2023-01 -> cohort 2023-01
    # C2 acquired 2023-02 -> cohort 2023-02
    # Sales in May (M+4 for C1, M+3 for C2), June (M+5 for C1)
    res = CustomerCohortAnalyzer.evaluate(multi_period_db, max_period_offset=6)

    assert res.total_cohorts == 2
    cohort_01 = next(c for c in res.cohorts if c.cohort_period == "2023-01")
    assert cohort_01.cohort_size == 1
    # Check M+4 (May)
    m4 = next(p for p in cohort_01.periods if p.period_index == 4)
    assert m4.active_customers == 1
    assert m4.retention_rate == 100.0
    assert m4.total_spend == Decimal("65.00")

    # Check M+5 (June)
    m5 = next(p for p in cohort_01.periods if p.period_index == 5)
    assert m5.active_customers == 1
    assert m5.retention_rate == 100.0
    assert m5.total_spend == Decimal("340.00")
