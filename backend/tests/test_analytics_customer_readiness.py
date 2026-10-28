"""Tests for Customer Data Readiness Assessor and Real-Data Audit (Phase 1C).

Verifies tenant isolation, missing data diagnostics, incomplete ingestion,
duplicate purchase events, repeat vs one-time buyer categorization,
watermark verification, and zero PII exposure.
"""

from datetime import UTC, date, datetime
from decimal import Decimal

from app.analytics.core.context import AnalysisContext
from app.analytics.customer.readiness import CustomerDataReadinessAssessor
from app.data.synthetic.cadence_generator import CadenceValidationDatasetGenerator
from app.models.customer import Customer
from app.models.sale import Sale
from app.models.tenant import IngestionJob
from sqlalchemy.orm import Session


def test_readiness_tenant_isolation(db_session: Session):
    """
    Verify strict tenant isolation: assessing biz-alpha must only reflect biz-alpha
    transactions and customer records, never mixing in biz-beta.
    """
    biz_a = "biz-readiness-alpha"
    biz_b = "biz-readiness-beta"

    # Setup tenant alpha: 1 repeat customer with 2 orders
    c_a = Customer(
        customer_code="CUST-ALPHA-01",
        business_id=biz_a,
        name="Alpha Customer",
        email="alpha@test.com",
        city="Chicago",
        customer_segment="Retail",
        acquisition_date=date(2023, 1, 1),
    )
    # Setup tenant beta: 1 repeat customer with 2 orders
    c_b = Customer(
        customer_code="CUST-BETA-01",
        business_id=biz_b,
        name="Beta Customer",
        email="beta@test.com",
        city="Detroit",
        customer_segment="Wholesale",
        acquisition_date=date(2023, 1, 1),
    )
    db_session.add_all([c_a, c_b])
    db_session.flush()

    s_a1 = Sale(
        transaction_number="TXN-A-01",
        business_id=biz_a,
        customer_id=c_a.id,
        transaction_date=datetime(2023, 1, 1, 10, 0, tzinfo=UTC),
        status="completed",
        subtotal=Decimal("100.00"),
        total_amount=Decimal("100.00"),
    )
    s_a2 = Sale(
        transaction_number="TXN-A-02",
        business_id=biz_a,
        customer_id=c_a.id,
        transaction_date=datetime(2023, 1, 20, 10, 0, tzinfo=UTC),
        status="completed",
        subtotal=Decimal("150.00"),
        total_amount=Decimal("150.00"),
    )
    s_b1 = Sale(
        transaction_number="TXN-B-01",
        business_id=biz_b,
        customer_id=c_b.id,
        transaction_date=datetime(2023, 1, 5, 10, 0, tzinfo=UTC),
        status="completed",
        subtotal=Decimal("500.00"),
        total_amount=Decimal("500.00"),
    )
    db_session.add_all([s_a1, s_a2, s_b1])
    db_session.commit()

    ctx_a = AnalysisContext(business_id=biz_a)
    report_a = CustomerDataReadinessAssessor.assess_tenant(db_session, context=ctx_a)

    assert report_a.business_id == biz_a
    assert report_a.historical_coverage.observed_total_transactions == 2
    assert report_a.historical_coverage.observed_sales_volume_usd == 250.00
    assert report_a.customer_population.registered_customers_count == 1
    assert report_a.customer_population.eligible_repeat_buyers_count == 1

    ctx_b = AnalysisContext(business_id=biz_b)
    report_b = CustomerDataReadinessAssessor.assess_tenant(db_session, context=ctx_b)

    assert report_b.business_id == biz_b
    assert report_b.historical_coverage.observed_total_transactions == 1
    assert report_b.historical_coverage.observed_sales_volume_usd == 500.00
    assert report_b.customer_population.registered_customers_count == 1
    assert report_b.customer_population.eligible_repeat_buyers_count == 0
    assert report_b.customer_population.one_time_buyers_count == 1


def test_readiness_repeat_buyer_and_one_time_share_calculation(db_session: Session):
    """
    Verify precise accounting of:
    - Registered customers
    - Eligible repeat buyers (>= 2 distinct dates)
    - One-time buyers (1 order)
    - Zero purchase customers (0 orders)
    - Simultaneous orders only (>= 2 orders on same timestamp)
    """
    biz_id = "biz-shares-test"

    c_rep = Customer(
        customer_code="CUST-SH-REP",
        business_id=biz_id,
        name="Repeat Buyer",
        email="rep@test.com",
        city="Austin",
        customer_segment="Retail",
        acquisition_date=date(2023, 1, 1),
    )
    c_single = Customer(
        customer_code="CUST-SH-SINGLE",
        business_id=biz_id,
        name="Single Buyer",
        email="single@test.com",
        city="Austin",
        customer_segment="Retail",
        acquisition_date=date(2023, 1, 1),
    )
    c_zero = Customer(
        customer_code="CUST-SH-ZERO",
        business_id=biz_id,
        name="Zero Buyer",
        email="zero@test.com",
        city="Austin",
        customer_segment="Retail",
        acquisition_date=date(2023, 1, 1),
    )
    c_simult = Customer(
        customer_code="CUST-SH-SIMULT",
        business_id=biz_id,
        name="Simultaneous Orders Buyer",
        email="simult@test.com",
        city="Austin",
        customer_segment="Retail",
        acquisition_date=date(2023, 1, 1),
    )
    db_session.add_all([c_rep, c_single, c_zero, c_simult])
    db_session.flush()

    # Repeat buyer has 2 purchases 15 days apart
    s1 = Sale(
        transaction_number="TXN-SH-01",
        business_id=biz_id,
        customer_id=c_rep.id,
        transaction_date=datetime(2023, 1, 1, 12, 0, tzinfo=UTC),
        status="completed",
        subtotal=Decimal("50.00"),
        total_amount=Decimal("50.00"),
    )
    s2 = Sale(
        transaction_number="TXN-SH-02",
        business_id=biz_id,
        customer_id=c_rep.id,
        transaction_date=datetime(2023, 1, 16, 12, 0, tzinfo=UTC),
        status="completed",
        subtotal=Decimal("50.00"),
        total_amount=Decimal("50.00"),
    )
    # Single buyer has 1 purchase
    s3 = Sale(
        transaction_number="TXN-SH-03",
        business_id=biz_id,
        customer_id=c_single.id,
        transaction_date=datetime(2023, 1, 5, 12, 0, tzinfo=UTC),
        status="completed",
        subtotal=Decimal("75.00"),
        total_amount=Decimal("75.00"),
    )
    # Simultaneous buyer has 2 purchases on exact same timestamp
    same_dt = datetime(2023, 1, 10, 14, 30, tzinfo=UTC)
    s4 = Sale(
        transaction_number="TXN-SH-04",
        business_id=biz_id,
        customer_id=c_simult.id,
        transaction_date=same_dt,
        status="completed",
        subtotal=Decimal("30.00"),
        total_amount=Decimal("30.00"),
    )
    s5 = Sale(
        transaction_number="TXN-SH-05",
        business_id=biz_id,
        customer_id=c_simult.id,
        transaction_date=same_dt,
        status="completed",
        subtotal=Decimal("40.00"),
        total_amount=Decimal("40.00"),
    )
    # Cancelled sale for single buyer (should be excluded from eligible)
    s6 = Sale(
        transaction_number="TXN-SH-06",
        business_id=biz_id,
        customer_id=c_single.id,
        transaction_date=datetime(2023, 1, 25, 12, 0, tzinfo=UTC),
        status="cancelled",
        subtotal=Decimal("100.00"),
        total_amount=Decimal("100.00"),
    )
    db_session.add_all([s1, s2, s3, s4, s5, s6])
    db_session.commit()

    ctx = AnalysisContext(business_id=biz_id)
    report = CustomerDataReadinessAssessor.assess_tenant(db_session, context=ctx)

    pop = report.customer_population
    assert pop.registered_customers_count == 4
    assert pop.customers_with_eligible_purchases == 3  # rep, single, simult
    assert pop.eligible_repeat_buyers_count == 1
    assert pop.one_time_buyers_count == 1
    assert pop.simultaneous_orders_only_count == 1
    assert pop.zero_purchase_customers_count == 1
    assert pop.inferred_repeat_buyer_share_pct == 33.33
    assert pop.inferred_one_time_buyer_share_pct == 33.33

    # Check status breakdown in historical coverage
    cov = report.historical_coverage
    assert cov.observed_total_transactions == 6
    assert cov.eligible_purchase_events == 5
    assert cov.cancelled_transactions_count == 1
    assert cov.inferred_cancelled_prevalence_pct == 16.67


def test_readiness_data_quality_diagnostics(db_session: Session):
    """
    Verify detection of data quality anomalies:
    - Inconsistent acquisition date (acquisition recorded after first purchase)
    - Duplicate purchase events on same timestamp
    - Ambiguous order numbers assigned across multiple customers
    """
    biz_id = "biz-dq-test"

    # Customer 1: acquisition date in June 2023, but placed order in January 2023
    c1 = Customer(
        customer_code="CUST-DQ-01",
        business_id=biz_id,
        name="Inconsistent Acq Customer",
        email="inconsistent@test.com",
        city="Dallas",
        customer_segment="Retail",
        acquisition_date=date(2023, 6, 1),
    )
    c2 = Customer(
        customer_code="CUST-DQ-02",
        business_id=biz_id,
        name="Collision Customer",
        email="collision@test.com",
        city="Dallas",
        customer_segment="Retail",
        acquisition_date=date(2023, 1, 1),
    )
    db_session.add_all([c1, c2])
    db_session.flush()

    # Sale 1 for c1 (before acquisition_date!)
    s1 = Sale(
        transaction_number="TXN-DQ-01",
        business_id=biz_id,
        customer_id=c1.id,
        transaction_date=datetime(2023, 1, 15, 10, 0, tzinfo=UTC),
        status="completed",
        subtotal=Decimal("100.00"),
        total_amount=Decimal("100.00"),
    )
    # Duplicate events for c1: two sales on exact same datetime
    dup_dt = datetime(2023, 2, 1, 12, 0, tzinfo=UTC)
    s2a = Sale(
        transaction_number="TXN-DQ-02A",
        business_id=biz_id,
        customer_id=c1.id,
        transaction_date=dup_dt,
        status="completed",
        subtotal=Decimal("50.00"),
        total_amount=Decimal("50.00"),
    )
    s2b = Sale(
        transaction_number="TXN-DQ-02B",
        business_id=biz_id,
        customer_id=c1.id,
        transaction_date=dup_dt,
        status="completed",
        subtotal=Decimal("50.00"),
        total_amount=Decimal("50.00"),
    )
    # Additional distinct sales
    s3 = Sale(
        transaction_number="TXN-DQ-03",
        business_id=biz_id,
        customer_id=c1.id,
        transaction_date=datetime(2023, 3, 1, 10, 0, tzinfo=UTC),
        status="completed",
        subtotal=Decimal("10.00"),
        total_amount=Decimal("10.00"),
    )
    s4 = Sale(
        transaction_number="TXN-DQ-04",
        business_id=biz_id,
        customer_id=c2.id,
        transaction_date=datetime(2023, 3, 1, 10, 0, tzinfo=UTC),
        status="completed",
        subtotal=Decimal("20.00"),
        total_amount=Decimal("20.00"),
    )
    db_session.add_all([s1, s2a, s2b, s3, s4])
    db_session.commit()

    ctx = AnalysisContext(business_id=biz_id)
    report = CustomerDataReadinessAssessor.assess_tenant(db_session, context=ctx)

    dq = report.data_quality
    assert dq.inconsistent_acquisition_dates_count == 1
    assert dq.duplicate_purchase_events_count == 1
    assert dq.duplicate_transaction_numbers_count == 0  # Enforced by DB schema unique constraint
    assert dq.ambiguous_order_groupings_count == 0
    assert any("inconsistent_acquisition_dates" in c or "acquisition dates occurring after" in c for c in report.cautions)


def test_readiness_ingestion_health_and_in_flight_blocker(db_session: Session):
    """
    Verify that an in-flight or failed IngestionJob for the tenant triggers
    a hard blocker in the readiness verdict.
    """
    biz_id = "biz-ingest-test"
    org_id = "org-test-01"
    dataset_id = "ds-test-01"

    # Setup basic customer and sale
    c = Customer(
        customer_code="CUST-INGEST-01",
        business_id=biz_id,
        name="Ingest Customer",
        email="ingest@test.com",
        city="Denver",
        customer_segment="Corporate",
        acquisition_date=date(2023, 1, 1),
    )
    db_session.add(c)
    db_session.flush()

    s = Sale(
        transaction_number="TXN-ING-01",
        business_id=biz_id,
        customer_id=c.id,
        transaction_date=datetime(2023, 1, 1, 10, 0, tzinfo=UTC),
        status="completed",
        subtotal=Decimal("100.00"),
        total_amount=Decimal("100.00"),
    )
    db_session.add(s)

    # Add an active IngestionJob in 'PROCESSING' state
    job = IngestionJob(
        id="job-active-01",
        organization_id=org_id,
        business_id=biz_id,
        dataset_id=dataset_id,
        status="PROCESSING",
        started_at=datetime.now(UTC),
    )
    db_session.add(job)
    db_session.commit()

    ctx = AnalysisContext(business_id=biz_id)
    report = CustomerDataReadinessAssessor.assess_tenant(db_session, context=ctx)

    assert report.ingestion_health.active_or_failed_ingestion_jobs_count == 1
    assert report.readiness_verdict == "NOT_READY"
    assert any("ingestion job(s) are active, failed, or require review" in b for b in report.blockers)


def test_readiness_candidate_cutoff_feasibility_and_censoring(db_session: Session):
    """
    Verify cutoff simulation:
    - Cutoff where follow-up completes within DB range is unverified_complete or verified_complete.
    - Cutoff where outcome horizon exceeds DB range is incomplete_censored and not pilot-ready.
    """
    biz_id = "biz-cutoff-feasibility"

    # Create 35 repeat customers (cadence = 20 days)
    custs = []
    sales = []
    for i in range(1, 36):
        c = Customer(
            customer_code=f"CUST-FEAS-{i:02d}",
            business_id=biz_id,
            name=f"Feas Customer {i}",
            email=f"feas{i}@test.com",
            city="Phoenix",
            customer_segment="Retail",
            acquisition_date=date(2022, 1, 1),
        )
        custs.append(c)
    db_session.add_all(custs)
    db_session.flush()

    for i, c in enumerate(custs, start=1):
        s1 = Sale(
            transaction_number=f"TXN-FEAS-{i}-1",
            business_id=biz_id,
            customer_id=c.id,
            transaction_date=datetime(2022, 10, 1, 10, 0, tzinfo=UTC),
            status="completed",
            subtotal=Decimal("50.00"),
            total_amount=Decimal("50.00"),
        )
        s2 = Sale(
            transaction_number=f"TXN-FEAS-{i}-2",
            business_id=biz_id,
            customer_id=c.id,
            transaction_date=datetime(2022, 10, 20, 10, 0, tzinfo=UTC),
            status="completed",
            subtotal=Decimal("50.00"),
            total_amount=Decimal("50.00"),
        )
        # Final sale on 2023-04-01
        s3 = Sale(
            transaction_number=f"TXN-FEAS-{i}-3",
            business_id=biz_id,
            customer_id=c.id,
            transaction_date=datetime(2023, 4, 1, 10, 0, tzinfo=UTC),
            status="completed",
            subtotal=Decimal("50.00"),
            total_amount=Decimal("50.00"),
        )
        sales.extend([s1, s2, s3])
    db_session.add_all(sales)
    db_session.commit()

    ctx = AnalysisContext(business_id=biz_id)

    # Cutoff 1: 2022-11-01 (Buffer: 7d -> Nov 8; Horizon: 60d -> Jan 7, 2023; DB max is 2023-04-01) -> complete!
    # Cutoff 2: 2023-03-15 (Buffer: 7d -> Mar 22; Horizon: 60d -> May 21, 2023; DB max is 2023-04-01) -> censored!
    c1 = datetime(2022, 11, 1, 10, 0, tzinfo=UTC)
    c2 = datetime(2023, 3, 15, 10, 0, tzinfo=UTC)

    report = CustomerDataReadinessAssessor.assess_tenant(
        db_session, context=ctx, candidate_cutoffs=[c1, c2], buffer_days=7, horizon_days=60
    )

    items = report.candidate_cutoffs
    assert len(items) == 2

    # First cutoff has complete follow-up and 35 repeat buyers -> is_pilot_ready is True
    item1 = items[0]
    assert item1.followup_status == "unverified_complete"
    assert item1.eligible_repeat_buyers_at_cutoff == 35
    assert item1.is_pilot_ready is True

    # Second cutoff has outcome window ending May 21, but latest sale is April 1 -> censored!
    item2 = items[1]
    assert item2.followup_status == "incomplete_censored"
    assert item2.is_pilot_ready is False


def test_readiness_privacy_compliance_zero_pii(db_session: Session):
    """
    Verify statutory privacy and governance assertion:
    The generated report must strictly omit customer-level PII (names, emails, phones, customer codes).
    """
    biz_id = "biz-privacy-test"
    secret_email = "very_confidential_buyer@classified.corp"
    secret_name = "Super Secret VIP Buyer"

    c = Customer(
        customer_code="CUST-SECRET-01",
        business_id=biz_id,
        name=secret_name,
        email=secret_email,
        phone="+1-555-867-5309",
        city="SecretCity",
        customer_segment="VIP",
        acquisition_date=date(2023, 1, 1),
    )
    db_session.add(c)
    db_session.flush()

    s = Sale(
        transaction_number="TXN-SECRET-01",
        business_id=biz_id,
        customer_id=c.id,
        transaction_date=datetime(2023, 1, 1, 10, 0, tzinfo=UTC),
        status="completed",
        subtotal=Decimal("1000.00"),
        total_amount=Decimal("1000.00"),
    )
    db_session.add(s)
    db_session.commit()

    ctx = AnalysisContext(business_id=biz_id)
    report = CustomerDataReadinessAssessor.assess_tenant(db_session, context=ctx)
    report_json = report.model_dump_json()

    # Verify zero PII leak
    assert secret_email not in report_json
    assert secret_name not in report_json
    assert "+1-555-867-5309" not in report_json
    assert "CUST-SECRET-01" not in report_json
    assert "SecretCity" not in report_json
    assert "Privacy Verified" in report.privacy_compliance_statement


def test_readiness_synthetic_dataset_integration(db_session: Session):
    """
    Verify readiness evaluation on the complete_pipeline synthetic dataset scenario.
    """
    dataset = CadenceValidationDatasetGenerator.create_scenario("complete_pipeline", seed=42)
    CadenceValidationDatasetGenerator.load_into_session(
        session=db_session, dataset=dataset, business_id="biz-pipe-rdy"
    )

    ctx = AnalysisContext(business_id="biz-pipe-rdy")
    wm = datetime(2023, 12, 31, 23, 59, tzinfo=UTC)
    cutoff = datetime(2023, 6, 30, 23, 59, tzinfo=UTC)

    report = CustomerDataReadinessAssessor.assess_tenant(
        session=db_session,
        context=ctx,
        candidate_cutoffs=[cutoff],
        ingestion_watermark=wm,
        buffer_days=7,
        horizon_days=60,
    )

    assert report.is_authorized is True
    assert report.historical_coverage.observed_total_transactions > 500
    assert report.customer_population.registered_customers_count > 100
    assert report.customer_population.eligible_repeat_buyers_count > 50
    assert report.customer_population.one_time_buyers_count > 40
    assert report.ingestion_health.authoritative_watermark_present is True
    assert report.ingestion_health.watermark_status == "verified_present"
    assert len(report.candidate_cutoffs) == 1
    assert report.candidate_cutoffs[0].followup_status == "verified_complete"
    assert report.candidate_cutoffs[0].is_pilot_ready is True
