"""Comprehensive unit tests for Authoritative Ingestion Watermarks (Phase 1F.2).

Verifies:
1. Watermark recording and audit ledger preservation.
2. Multi-source minimum complete-through calculation.
3. Incomplete, missing, or invalidated source gaps blocking tenant completeness.
4. In-flight or failed ingestion jobs blocking watermark advancement.
5. Delayed transactions and backfills triggering automatic invalidation.
6. Strict cross-tenant isolation in watermark contracts.
7. Historical cadence validation honoring watermarks (right-censoring vs verified complete).
8. Safeguards preventing unverified follow-up from being silently treated as negative customer outcomes.
9. Readiness assessor integration with multi-source watermark evaluation.
"""

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from app.analytics.core.context import AnalysisContext
from app.analytics.customer.readiness import CustomerDataReadinessAssessor
from app.analytics.customer.validation import HistoricalCadenceValidator
from app.models.customer import Customer
from app.models.sale import Sale
from app.models.tenant import Business, IngestionJob, Organization, UploadedDataset
from app.models.watermark import TenantIngestionWatermark
from app.services.watermark_service import WatermarkContract, WatermarkService
from sqlalchemy.orm import Session


@pytest.fixture
def test_tenant(db_session: Session) -> tuple[Organization, Business]:
    """Create isolated test organization and business."""
    org = Organization(
        id=f"org-wm-test-{uuid4().hex[:8]}",
        name="Watermark Test Org",
        slug=f"org-wm-{uuid4().hex[:8]}",
    )
    biz = Business(
        id=f"biz-wm-test-{uuid4().hex[:8]}",
        organization_id=org.id,
        name="Watermark Retail Business",
    )
    db_session.add_all([org, biz])
    db_session.commit()
    return org, biz


def test_watermark_record_and_ledger_auditability(db_session: Session, test_tenant: tuple[Organization, Business]):
    """Verify watermark creation and audit trail preservation on updates."""
    _, biz = test_tenant

    # 1. Record initial watermark for POS source through 2023-06-30
    wm1 = WatermarkService.record_watermark(
        session=db_session,
        contract=WatermarkContract(
            business_id=biz.id,
            source_id="pos",
            complete_through_dt=datetime(2023, 6, 30, 23, 59, tzinfo=UTC),
            provenance_type="accounting_period_close",
            metadata_json={"batch_id": "BATCH-001", "records_verified": 5000},
        ),
    )
    db_session.commit()

    assert wm1.is_active is True
    assert wm1.verification_status == "verified"
    assert wm1.complete_through_utc == datetime(2023, 6, 30, 23, 59, tzinfo=UTC)

    # 2. Advance watermark for POS through 2023-07-31
    wm2 = WatermarkService.record_watermark(
        session=db_session,
        contract=WatermarkContract(
            business_id=biz.id,
            source_id="pos",
            complete_through_dt=datetime(2023, 7, 31, 23, 59, tzinfo=UTC),
            provenance_type="accounting_period_close",
            metadata_json={"batch_id": "BATCH-002", "records_verified": 5200},
        ),
    )
    db_session.commit()

    # Verify audit trail: wm1 is still in DB, but deactivated
    all_wms = db_session.query(TenantIngestionWatermark).filter_by(
        business_id=biz.id, source_id="pos"
    ).order_by(TenantIngestionWatermark.complete_through_dt.asc()).all()

    assert len(all_wms) == 2
    assert all_wms[0].id == wm1.id
    assert all_wms[0].is_active is False
    assert all_wms[1].id == wm2.id
    assert all_wms[1].is_active is True


def test_multiple_data_sources_effective_minimum_watermark(db_session: Session, test_tenant: tuple[Organization, Business]):
    """Verify that multiple data sources combine via minimum complete-through date."""
    _, biz = test_tenant

    # Source 1: eCommerce complete through 2023-08-31
    WatermarkService.record_watermark(
        session=db_session,
        contract=WatermarkContract(
            business_id=biz.id,
            source_id="ecommerce",
            complete_through_dt=datetime(2023, 8, 31, 23, 59, tzinfo=UTC),
        ),
    )
    # Source 2: In-store POS complete through 2023-06-30 (limiting source)
    WatermarkService.record_watermark(
        session=db_session,
        contract=WatermarkContract(
            business_id=biz.id,
            source_id="pos",
            complete_through_dt=datetime(2023, 6, 30, 23, 59, tzinfo=UTC),
        ),
    )
    # Source 3: Wholesale complete through 2023-07-15
    WatermarkService.record_watermark(
        session=db_session,
        contract=WatermarkContract(
            business_id=biz.id,
            source_id="wholesale",
            complete_through_dt=datetime(2023, 7, 15, 23, 59, tzinfo=UTC),
        ),
    )
    db_session.commit()

    effective = WatermarkService.get_effective_tenant_watermark(db_session, biz.id)

    assert effective.is_verified is True
    assert effective.status == "verified_complete"
    assert effective.effective_complete_through_dt == datetime(2023, 6, 30, 23, 59, tzinfo=UTC)
    assert effective.earliest_source_id == "pos"
    assert len(effective.source_watermarks) == 3


def test_required_sources_gap_blocks_tenant_watermark(db_session: Session, test_tenant: tuple[Organization, Business]):
    """Verify that a missing required source blocks tenant-level completeness certification."""
    _, biz = test_tenant

    # Only ecommerce and pos are verified; wholesale has never recorded a watermark
    WatermarkService.record_watermark(
        session=db_session,
        contract=WatermarkContract(
            business_id=biz.id,
            source_id="ecommerce",
            complete_through_dt=datetime(2023, 8, 31, 23, 59, tzinfo=UTC),
        ),
    )
    WatermarkService.record_watermark(
        session=db_session,
        contract=WatermarkContract(
            business_id=biz.id,
            source_id="pos",
            complete_through_dt=datetime(2023, 8, 31, 23, 59, tzinfo=UTC),
        ),
    )
    db_session.commit()

    # Query with required sources including wholesale
    effective = WatermarkService.get_effective_tenant_watermark(
        db_session, biz.id, required_sources=["ecommerce", "pos", "wholesale"]
    )

    assert effective.is_verified is False
    assert effective.status == "incomplete_watermark_gap"
    assert "wholesale" in effective.unverified_sources
    assert effective.effective_complete_through_dt is None
    assert any("wholesale" in r for r in effective.blocking_reasons)


def test_in_flight_or_failed_ingestion_blocks_watermark(db_session: Session, test_tenant: tuple[Organization, Business]):
    """Verify that an unresolved or failed ingestion job blocks completeness verification."""
    org, biz = test_tenant

    # Record verified watermark
    WatermarkService.record_watermark(
        session=db_session,
        contract=WatermarkContract(
            business_id=biz.id,
            source_id="pos",
            complete_through_dt=datetime(2023, 8, 31, 23, 59, tzinfo=UTC),
        ),
    )

    # Attach an uploaded dataset and a FAILED IngestionJob
    ds = UploadedDataset(
        business_id=biz.id,
        organization_id=org.id,
        filename="sales_delayed.csv",
        file_type="csv",
        storage_key="s3://nexus/delayed.csv",
        file_size_bytes=1024,
    )
    db_session.add(ds)
    db_session.flush()

    failed_job = IngestionJob(
        organization_id=org.id,
        business_id=biz.id,
        dataset_id=ds.id,
        status="FAILED",
        error_message="Connection timed out during bulk insertion",
    )
    db_session.add(failed_job)
    db_session.commit()

    effective = WatermarkService.get_effective_tenant_watermark(db_session, biz.id)

    assert effective.is_verified is False
    assert effective.status == "incomplete_in_flight"
    assert effective.in_flight_or_failed_jobs_count == 1
    assert any("FAILED" in r or "failed" in r.lower() for r in effective.blocking_reasons)


def test_delayed_transactions_and_backfill_invalidates_watermark(db_session: Session, test_tenant: tuple[Organization, Business]):
    """Verify that late-arriving backfilled transactions automatically invalidate active watermarks."""
    _, biz = test_tenant

    # 1. Certify completeness through 2023-06-30
    wm = WatermarkService.record_watermark(
        session=db_session,
        contract=WatermarkContract(
            business_id=biz.id,
            source_id="pos",
            complete_through_dt=datetime(2023, 6, 30, 23, 59, tzinfo=UTC),
        ),
    )
    db_session.commit()
    assert wm.verification_status == "verified"
    assert wm.is_active is True

    # 2. Simulate backfill batch containing transaction from 2023-05-10
    backfill_dates = [
        datetime(2023, 5, 10, 14, 30, tzinfo=UTC),
        datetime(2023, 5, 12, 10, 0, tzinfo=UTC),
    ]

    invalidated = WatermarkService.detect_backfill_and_handle(
        session=db_session,
        business_id=biz.id,
        source_id="pos",
        transaction_dates=backfill_dates,
        job_id="JOB-BACKFILL-01",
    )
    db_session.commit()

    assert invalidated is True

    # Inspect watermark state
    db_session.refresh(wm)
    assert wm.verification_status == "invalidated"
    assert "Backfill detected" in (wm.invalidation_reason or "")

    # Effective watermark is now invalidated
    effective = WatermarkService.get_effective_tenant_watermark(db_session, biz.id)
    assert effective.is_verified is False
    assert effective.status == "invalidated"



def test_tenant_isolation_in_watermarks(db_session: Session):
    """Verify strict tenant isolation across watermark queries and invalidations."""
    org1 = Organization(id=f"org-iso-1-{uuid4().hex[:6]}", name="Org 1", slug=f"org1-{uuid4().hex[:6]}")
    biz1 = Business(id=f"biz-iso-1-{uuid4().hex[:6]}", organization_id=org1.id, name="Biz 1")
    org2 = Organization(id=f"org-iso-2-{uuid4().hex[:6]}", name="Org 2", slug=f"org2-{uuid4().hex[:6]}")
    biz2 = Business(id=f"biz-iso-2-{uuid4().hex[:6]}", organization_id=org2.id, name="Biz 2")
    db_session.add_all([org1, biz1, org2, biz2])
    db_session.commit()

    # Record watermark for Biz 1 only
    WatermarkService.record_watermark(
        session=db_session,
        contract=WatermarkContract(
            business_id=biz1.id,
            source_id="pos",
            complete_through_dt=datetime(2023, 9, 30, 23, 59, tzinfo=UTC),
        ),
    )
    db_session.commit()

    eff1 = WatermarkService.get_effective_tenant_watermark(db_session, biz1.id)
    eff2 = WatermarkService.get_effective_tenant_watermark(db_session, biz2.id)

    assert eff1.is_verified is True
    assert eff1.status == "verified_complete"

    assert eff2.is_verified is False
    assert eff2.status == "unverified_missing"
    assert len(eff2.source_watermarks) == 0


def test_historical_validation_with_watermark_exceeding_and_preceding_horizon(
    db_session: Session, test_tenant: tuple[Organization, Business]
):
    """Verify that historical validation uses watermarks to distinguish verified complete vs right-censored."""
    _, biz = test_tenant
    ctx = AnalysisContext(business_id=biz.id)

    c = Customer(
        customer_code="CUST-WM-VAL",
        business_id=biz.id,
        name="Validation Customer",
        email="val@test.com",
        city="Denver",
        customer_segment="Retail",
        acquisition_date=date(2023, 1, 1),
    )
    db_session.add(c)
    db_session.flush()

    s1 = Sale(
        transaction_number=f"TXN-WM-V1-{uuid4().hex[:6]}",
        business_id=biz.id,
        customer_id=c.id,
        transaction_date=datetime(2023, 1, 10, 10, 0, tzinfo=UTC),
        status="completed",
        subtotal=Decimal("100.00"),
        total_amount=Decimal("100.00"),
    )
    s2 = Sale(
        transaction_number=f"TXN-WM-V2-{uuid4().hex[:6]}",
        business_id=biz.id,
        customer_id=c.id,
        transaction_date=datetime(2023, 1, 20, 10, 0, tzinfo=UTC),
        status="completed",
        subtotal=Decimal("100.00"),
        total_amount=Decimal("100.00"),
    )
    # Stray order far in future
    s_far = Sale(
        transaction_number=f"TXN-WM-VFAR-{uuid4().hex[:6]}",
        business_id=biz.id,
        customer_id=c.id,
        transaction_date=datetime(2023, 12, 1, 10, 0, tzinfo=UTC),
        status="completed",
        subtotal=Decimal("100.00"),
        total_amount=Decimal("100.00"),
    )
    db_session.add_all([s1, s2, s_far])
    db_session.commit()

    cutoff = datetime(2023, 1, 31, 23, 59, tzinfo=UTC)
    # buffer=7, horizon=60 -> Outcome window ends 2023-04-08 23:59 UTC

    # Case A: Watermark recorded at 2023-03-31 (precedes 2023-04-08)
    WatermarkService.record_watermark(
        session=db_session,
        contract=WatermarkContract(
            business_id=biz.id,
            source_id="default",
            complete_through_dt=datetime(2023, 3, 31, 23, 59, tzinfo=UTC),
        ),
    )
    db_session.commit()

    res_censored = HistoricalCadenceValidator.evaluate_cutoff(
        session=db_session,
        context=ctx,
        cutoff_date=cutoff,
        buffer_days=7,
        horizon_days=60,
    )
    assert res_censored.is_complete_followup is False
    assert res_censored.is_followup_verified is True
    assert res_censored.followup_status == "incomplete_censored"
    assert "Authoritative ingestion watermark" in (res_censored.censoring_reason or "")

    # Case B: Watermark updated to 2023-04-15 (covers outcome horizon)
    WatermarkService.record_watermark(
        session=db_session,
        contract=WatermarkContract(
            business_id=biz.id,
            source_id="default",
            complete_through_dt=datetime(2023, 4, 15, 23, 59, tzinfo=UTC),
        ),
    )
    db_session.commit()

    res_verified = HistoricalCadenceValidator.evaluate_cutoff(
        session=db_session,
        context=ctx,
        cutoff_date=cutoff,
        buffer_days=7,
        horizon_days=60,
    )
    assert res_verified.is_complete_followup is True
    assert res_verified.is_followup_verified is True
    assert res_verified.followup_status == "verified_complete"
    assert res_verified.censoring_reason is None


def test_unverified_followup_never_silently_treated_as_negative_outcome(
    db_session: Session, test_tenant: tuple[Organization, Business]
):
    """Verify that unverified follow-up carries explicit flags and warnings, and with require_verified_watermark=True is censored."""
    _, biz = test_tenant
    ctx = AnalysisContext(business_id=biz.id)

    c = Customer(
        customer_code="CUST-UNVERIFIED-SAFETY",
        business_id=biz.id,
        name="Safety Customer",
        email="safe@test.com",
        city="Denver",
        customer_segment="Retail",
        acquisition_date=date(2023, 1, 1),
    )
    db_session.add(c)
    db_session.flush()

    s1 = Sale(
        transaction_number=f"TXN-SAFE-01-{uuid4().hex[:6]}",
        business_id=biz.id,
        customer_id=c.id,
        transaction_date=datetime(2023, 1, 5, 10, 0, tzinfo=UTC),
        status="completed",
        subtotal=Decimal("50.00"),
        total_amount=Decimal("50.00"),
    )
    s2 = Sale(
        transaction_number=f"TXN-SAFE-02-{uuid4().hex[:6]}",
        business_id=biz.id,
        customer_id=c.id,
        transaction_date=datetime(2023, 1, 15, 10, 0, tzinfo=UTC),
        status="completed",
        subtotal=Decimal("50.00"),
        total_amount=Decimal("50.00"),
    )
    # Stray order far in future so MAX(date) covers outcome window
    s_far = Sale(
        transaction_number=f"TXN-SAFE-FAR-{uuid4().hex[:6]}",
        business_id=biz.id,
        customer_id=c.id,
        transaction_date=datetime(2023, 10, 1, 10, 0, tzinfo=UTC),
        status="completed",
        subtotal=Decimal("50.00"),
        total_amount=Decimal("50.00"),
    )
    db_session.add_all([s1, s2, s_far])
    db_session.commit()

    cutoff = datetime(2023, 1, 20, 10, 0, tzinfo=UTC)

    # 1. Standard mode: unverified_complete produces explicit unverified flags
    res = HistoricalCadenceValidator.evaluate_cutoff(
        session=db_session,
        context=ctx,
        cutoff_date=cutoff,
        buffer_days=7,
        horizon_days=60,
        include_customer_records=True,
    )

    assert res.is_complete_followup is True
    assert res.is_followup_verified is False
    assert res.followup_status == "unverified_complete"

    # Verify customer records carry unverified flags
    rec = res.customer_records[0]
    assert rec.is_followup_verified is False
    assert rec.unverified_negative_outcome is True  # Did not repurchase, but unverified!

    # Verify warning in limitations
    assert any("UNVERIFIED OUTCOMES NOTICE" in lim for lim in res.limitations)

    # 2. Strict mode: require_verified_watermark=True censors unverified follow-up
    res_strict = HistoricalCadenceValidator.evaluate_cutoff(
        session=db_session,
        context=ctx,
        cutoff_date=cutoff,
        buffer_days=7,
        horizon_days=60,
        include_customer_records=True,
        require_verified_watermark=True,
    )

    assert res_strict.is_complete_followup is False
    assert res_strict.is_followup_verified is False
    assert res_strict.followup_status == "incomplete_censored"
    assert "require_verified_watermark=True" in (res_strict.censoring_reason or "")
    rec_strict = res_strict.customer_records[0]
    assert rec_strict.outcome_no_purchase is None  # Censored, NOT negative outcome!
    assert rec_strict.is_censored is True


def test_readiness_assessor_multi_source_and_invalidated_watermark(
    db_session: Session, test_tenant: tuple[Organization, Business]
):
    """Verify CustomerDataReadinessAssessor integrates with multi-source watermarks."""
    _, biz = test_tenant
    ctx = AnalysisContext(business_id=biz.id)

    # Create 35 repeat customers
    for i in range(35):
        c = Customer(
            customer_code=f"CUST-READINESS-{i:03d}",
            business_id=biz.id,
            name=f"Customer {i}",
            email=f"readiness_{i:03d}@test.com",
            city="Denver",
            customer_segment="Retail",
            acquisition_date=date(2023, 1, 1),
        )
        db_session.add(c)
        db_session.flush()

        s1 = Sale(
            transaction_number=f"TXN-R1-{i:03d}-{uuid4().hex[:4]}",
            business_id=biz.id,
            customer_id=c.id,
            transaction_date=datetime(2023, 1, 5, 10, 0, tzinfo=UTC),
            status="completed",
            subtotal=Decimal("50.00"),
            total_amount=Decimal("50.00"),
        )
        s2 = Sale(
            transaction_number=f"TXN-R2-{i:03d}-{uuid4().hex[:4]}",
            business_id=biz.id,
            customer_id=c.id,
            transaction_date=datetime(2023, 2, 5, 10, 0, tzinfo=UTC),
            status="completed",
            subtotal=Decimal("50.00"),
            total_amount=Decimal("50.00"),
        )
        s3 = Sale(
            transaction_number=f"TXN-R3-{i:03d}-{uuid4().hex[:4]}",
            business_id=biz.id,
            customer_id=c.id,
            transaction_date=datetime(2023, 5, 1, 10, 0, tzinfo=UTC),
            status="completed",
            subtotal=Decimal("50.00"),
            total_amount=Decimal("50.00"),
        )
        db_session.add_all([s1, s2, s3])

    db_session.commit()

    # Step 1: Initial state without watermark
    report_unv = CustomerDataReadinessAssessor.assess_tenant(
        session=db_session,
        context=ctx,
        candidate_cutoffs=[datetime(2023, 2, 10, tzinfo=UTC)],
    )
    assert report_unv.ingestion_health.authoritative_watermark_present is False
    assert report_unv.ingestion_health.watermark_status == "unverified_missing"
    assert any("Authoritative ingestion watermark is absent" in c for c in report_unv.cautions)

    # Step 2: Record verified watermark covering outcome horizon
    WatermarkService.record_watermark(
        session=db_session,
        contract=WatermarkContract(
            business_id=biz.id,
            source_id="pos",
            complete_through_dt=datetime(2023, 5, 15, tzinfo=UTC),
        ),
    )
    db_session.commit()

    report_ver = CustomerDataReadinessAssessor.assess_tenant(
        session=db_session,
        context=ctx,
        candidate_cutoffs=[datetime(2023, 2, 10, tzinfo=UTC)],
    )
    assert report_ver.ingestion_health.authoritative_watermark_present is True
    assert report_ver.ingestion_health.watermark_status == "verified_present"
    assert report_ver.candidate_cutoffs[0].followup_status == "verified_complete"
    assert report_ver.candidate_cutoffs[0].is_verified is True

    # Step 3: Invalidate watermark
    WatermarkService.invalidate_watermark(
        session=db_session,
        business_id=biz.id,
        source_id="pos",
        reason="Discrepancy in POS close report",
    )
    db_session.commit()

    report_inv = CustomerDataReadinessAssessor.assess_tenant(
        session=db_session,
        context=ctx,
        candidate_cutoffs=[datetime(2023, 2, 10, tzinfo=UTC)],
    )
    assert report_inv.ingestion_health.effective_watermark_status == "invalidated"
    assert report_inv.candidate_cutoffs[0].followup_status == "invalidated_watermark"
    assert any("invalidated" in b for b in report_inv.blockers)


def test_successful_upload_alone_does_not_advance_watermark(
    db_session: Session, test_tenant: tuple[Organization, Business]
):
    """Verify that a successful file upload alone does not advance or certify historical completeness."""
    org, biz = test_tenant

    # Upload dataset and complete ingestion job without explicit completeness certification
    ds = UploadedDataset(
        business_id=biz.id,
        organization_id=org.id,
        filename="sales_batch_2023.csv",
        file_type="csv",
        storage_key="s3://nexus/sales.csv",
        file_size_bytes=4096,
        readiness_status="READY",
    )
    db_session.add(ds)
    db_session.flush()

    job = IngestionJob(
        organization_id=org.id,
        business_id=biz.id,
        dataset_id=ds.id,
        status="COMPLETED",
        target_entity="Sale",
        rows_processed=150,
    )
    db_session.add(job)
    db_session.commit()

    # Verify that watermark remains unverified (no automatic inference from file upload alone)
    effective = WatermarkService.get_effective_tenant_watermark(db_session, biz.id)
    assert effective.is_verified is False
    assert effective.status == "unverified_missing"
    assert effective.effective_complete_through_dt is None


def test_data_gateway_ingest_detects_backfill_and_invalidates_watermark(
    db_session: Session, test_tenant: tuple[Organization, Business]
):
    """Verify that DataGatewayService backfill detection invalidates active watermarks upon ingesting historical orders."""
    org, biz = test_tenant

    # 1. Certify watermark through 2023-06-30
    wm = WatermarkService.record_watermark(
        session=db_session,
        contract=WatermarkContract(
            business_id=biz.id,
            source_id="sales_batch_2023.csv",
            complete_through_dt=datetime(2023, 6, 30, 23, 59, tzinfo=UTC),
        ),
    )
    db_session.commit()
    assert wm.is_active is True
    assert wm.verification_status == "verified"

    # 2. Ingest backfilled sales with date 2023-04-10
    ds = UploadedDataset(
        business_id=biz.id,
        organization_id=org.id,
        filename="sales_batch_2023.csv",
        file_type="csv",
        storage_key="s3://nexus/sales_backfill.csv",
        file_size_bytes=2048,
    )
    db_session.add(ds)
    db_session.flush()

    job = IngestionJob(
        organization_id=org.id,
        business_id=biz.id,
        dataset_id=ds.id,
        status="COMPLETED",
        target_entity="Sale",
        rows_processed=1,
    )
    db_session.add(job)

    c = Customer(
        customer_code="CUST-BACKFILL-01",
        business_id=biz.id,
        name="Backfill Customer",
        email="bf@test.com",
        city="Denver",
        customer_segment="Retail",
        acquisition_date=date(2023, 1, 1),
    )
    db_session.add(c)
    db_session.flush()

    s = Sale(
        transaction_number=f"TXN-BF-{uuid4().hex[:6]}",
        business_id=biz.id,
        customer_id=c.id,
        transaction_date=datetime(2023, 4, 10, 10, 0, tzinfo=UTC),
        status="completed",
        subtotal=Decimal("75.00"),
        total_amount=Decimal("75.00"),
    )
    db_session.add(s)

    # Trigger backfill detection
    invalidated = WatermarkService.detect_backfill_and_handle(
        session=db_session,
        business_id=biz.id,
        source_id="sales_batch_2023.csv",
        transaction_dates=[s.transaction_date],
        job_id=job.id,
    )
    db_session.commit()

    assert invalidated is True

    # Confirm watermark is invalidated
    db_session.refresh(wm)
    assert wm.verification_status == "invalidated"
    assert "Backfill detected" in (wm.invalidation_reason or "")

    effective = WatermarkService.get_effective_tenant_watermark(db_session, biz.id)
    assert effective.is_verified is False
    assert effective.status == "invalidated"


def test_database_level_active_watermark_unique_constraint(
    db_session: Session, test_tenant: tuple[Organization, Business]
):
    """Verify partial unique index blocks duplicate active watermarks for same tenant and source."""
    from sqlalchemy.exc import IntegrityError

    _, biz = test_tenant

    wm1 = TenantIngestionWatermark(
        id=f"wm-act-1-{uuid4().hex[:6]}",
        business_id=biz.id,
        source_id="shopify",
        complete_through_dt=datetime(2023, 5, 1, 0, 0, tzinfo=UTC),
        recorded_at=datetime.now(UTC),
        verification_status="verified",
        is_active=True,
    )
    db_session.add(wm1)
    db_session.commit()

    # Second active watermark for same tenant and source must be blocked by database unique index
    wm2 = TenantIngestionWatermark(
        id=f"wm-act-2-{uuid4().hex[:6]}",
        business_id=biz.id,
        source_id="shopify",
        complete_through_dt=datetime(2023, 6, 1, 0, 0, tzinfo=UTC),
        recorded_at=datetime.now(UTC),
        verification_status="verified",
        is_active=True,
    )
    db_session.add(wm2)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()

    # Inactive watermark for same tenant and source is allowed (audit ledger)
    wm3 = TenantIngestionWatermark(
        id=f"wm-inact-3-{uuid4().hex[:6]}",
        business_id=biz.id,
        source_id="shopify",
        complete_through_dt=datetime(2023, 4, 1, 0, 0, tzinfo=UTC),
        recorded_at=datetime.now(UTC),
        verification_status="verified",
        is_active=False,
    )
    db_session.add(wm3)
    db_session.commit()
    assert wm3.id is not None


def test_alembic_migration_017_upgrade_downgrade_sqlite():
    """Verify migration 017 upgrade and downgrade execution on transactional SQLite engine."""
    import importlib.util
    from pathlib import Path

    import sqlalchemy as sa
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from app.models.base import Base
    from app.models.tenant import Business, IngestionJob, Organization

    versions_dir = Path(__file__).resolve().parent.parent / "alembic" / "versions"
    module_path = versions_dir / "017_phase1f2_authoritative_ingestion_watermark.py"
    spec = importlib.util.spec_from_file_location("mod_017", module_path)
    assert spec is not None and spec.loader is not None
    mod_017 = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod_017)

    eng = sa.create_engine("sqlite:///:memory:")
    with eng.connect() as conn:
        # Create base tables required by migration 017
        Base.metadata.create_all(conn, tables=[Organization.__table__, Business.__table__, IngestionJob.__table__])
        conn.commit()

        # Configure migration context
        ctx = MigrationContext.configure(conn)

        # 1. Test upgrade
        with Operations.context(ctx):
            mod_017.upgrade()
        conn.commit()

        insp = sa.inspect(conn)
        assert insp.has_table("tenant_ingestion_watermarks")
        cols = {c["name"] for c in insp.get_columns("tenant_ingestion_watermarks")}
        assert "complete_through_dt" in cols
        assert "business_id" in cols
        assert "is_active" in cols

        # 2. Test downgrade
        with Operations.context(ctx):
            mod_017.downgrade()
        conn.commit()

        insp = sa.inspect(conn)
        assert not insp.has_table("tenant_ingestion_watermarks")

        # 3. Test re-upgrade
        with Operations.context(ctx):
            mod_017.upgrade()
        conn.commit()

        insp = sa.inspect(conn)
        assert insp.has_table("tenant_ingestion_watermarks")



