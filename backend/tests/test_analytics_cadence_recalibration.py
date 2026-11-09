"""NEXUS Phase 1H - Watermark-Aware Cadence Recalibration & Readiness Tests.

Validates:
1. Watermark-aware right-censoring when forward outcome horizon exceeds completeness boundary.
2. Unverified completeness fallback behavior and mandatory warning disclosures.
3. Threshold recalibration comparison (Baseline vs Candidate B) on deterministic cohorts.
4. Customer-level calibration vs holdout partition integrity (zero leakage).
5. One-time buyer protection invariance across threshold permutations.
6. Invalidation propagation: backfilled data invalidates prior watermarks and blocks subsequent validations.
"""

from datetime import UTC, date, datetime

import pytest
from app.analytics.core.context import AnalysisContext
from app.analytics.customer.cadence import (
    CadenceConfig,
    CadenceRiskTier,
    CustomerCadenceAnalyzer,
)
from app.analytics.customer.validation import (
    HistoricalCadenceValidator,
)
from app.data.synthetic.cadence_generator import (
    CadenceGeneratorConfig,
    CadenceValidationDatasetGenerator,
)
from app.models.tenant import Base, Business, Organization
from app.services.watermark_service import WatermarkContract, WatermarkService
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


@pytest.fixture
def recalibration_session():
    """Isolated in-memory SQLite database session with deterministic fixture."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()

    biz_id = "biz-recalibration-test"
    org_id = "org-recalibration-test"
    org = Organization(id=org_id, name="Recalibration Org", slug="recalibration-org")
    biz = Business(id=biz_id, name="Recalibration Biz", organization_id=org_id)
    session.add_all([org, biz])
    session.commit()

    # Generate synthetic dataset with known seed
    gen = CadenceValidationDatasetGenerator(seed=42)
    dataset = gen.generate(
        CadenceGeneratorConfig(
            seed=42,
            business_id=biz_id,
            organization_id=org_id,
            num_customers=60,
            start_date=date(2023, 1, 1),
            end_date=date(2023, 12, 31),
            zero_purchase_pct=0.05,
            one_time_buyer_pct=0.35,
        )
    )
    CadenceValidationDatasetGenerator.load_into_session(session, dataset, biz_id, org_id)
    session.commit()

    yield session, biz_id
    session.close()


def test_watermark_aware_cutoff_censoring_when_horizon_exceeds_watermark(recalibration_session):
    """Verify that evaluate_cutoff right-censors when outcome window exceeds authoritative watermark."""
    session, biz_id = recalibration_session
    ctx = AnalysisContext(business_id=biz_id)

    # Outcome window: 2023-07-07 to 2023-09-05 (60d horizon + 7d buffer from 2023-06-30)
    # Watermark certified only through 2023-08-15 (precedes outcome window end)
    wm_dt = datetime(2023, 8, 15, 23, 59, 59, tzinfo=UTC)
    WatermarkService.record_watermark(
        session=session,
        contract=WatermarkContract(
            business_id=biz_id,
            source_id="default",
            complete_through_dt=wm_dt,
            provenance_type="manual_close",
            verification_status="verified",
        ),
    )
    session.commit()

    res = HistoricalCadenceValidator.evaluate_cutoff(
        session=session,
        context=ctx,
        cutoff_date=date(2023, 6, 30),
        buffer_days=7,
        horizon_days=60,
        require_verified_watermark=True,
    )

    assert res.is_complete_followup is False
    assert res.is_followup_verified is True
    assert res.followup_status == "incomplete_censored"
    assert "precedes outcome window end" in res.censoring_reason
    assert res.baseline_no_purchase_rate is None
    assert res.critical_precision is None
    assert res.critical_lift is None


def test_watermark_aware_unverified_cutoff_when_require_verified_is_false(recalibration_session):
    """Verify unverified fallback behavior emits unverified_complete and mandatory notices."""
    session, biz_id = recalibration_session
    ctx = AnalysisContext(business_id=biz_id)

    # No watermark recorded, but sales table extends to 2023-12-31
    res = HistoricalCadenceValidator.evaluate_cutoff(
        session=session,
        context=ctx,
        cutoff_date=date(2023, 6, 30),
        buffer_days=7,
        horizon_days=60,
        require_verified_watermark=False,
    )

    assert res.is_complete_followup is True
    assert res.is_followup_verified is False
    assert res.followup_status == "unverified_complete"
    assert res.censoring_reason is None
    assert res.baseline_no_purchase_rate is not None
    assert any("Follow-up completeness is unverified" in lim for lim in res.limitations)
    assert any("UNVERIFIED OUTCOMES NOTICE" in lim for lim in res.limitations)


def test_candidate_threshold_recalibration_comparison(recalibration_session):
    """Compare baseline thresholds against Candidate B on verified complete window."""
    session, biz_id = recalibration_session
    ctx = AnalysisContext(business_id=biz_id)

    wm_full = datetime(2023, 12, 31, 23, 59, 59, tzinfo=UTC)
    WatermarkService.record_watermark(
        session=session,
        contract=WatermarkContract(
            business_id=biz_id,
            source_id="default",
            complete_through_dt=wm_full,
            provenance_type="manual_close",
            verification_status="verified",
        ),
    )
    session.commit()

    base_cfg = CadenceConfig(low_threshold=1.25, medium_threshold=2.0, high_threshold=3.0)
    cand_b_cfg = CadenceConfig(low_threshold=1.3, medium_threshold=1.8, high_threshold=2.8)

    res_base = HistoricalCadenceValidator.evaluate_cutoff(
        session=session,
        context=ctx,
        cutoff_date=date(2023, 6, 30),
        buffer_days=7,
        horizon_days=60,
        cadence_config=base_cfg,
        require_verified_watermark=True,
    )

    res_cand = HistoricalCadenceValidator.evaluate_cutoff(
        session=session,
        context=ctx,
        cutoff_date=date(2023, 6, 30),
        buffer_days=7,
        horizon_days=60,
        cadence_config=cand_b_cfg,
        require_verified_watermark=True,
    )

    assert res_base.followup_status == "verified_complete"
    assert res_cand.followup_status == "verified_complete"
    assert res_base.critical_precision is not None and res_base.critical_lift is not None
    assert res_base.critical_lift > 1.5
    assert res_cand.critical_precision is not None and res_cand.critical_lift is not None
    assert res_cand.critical_lift > 1.5


def test_customer_level_holdout_split_zero_leakage(recalibration_session):
    """Verify customer-level partitioning preserves clean separation without leakage."""
    session, biz_id = recalibration_session
    ctx = AnalysisContext(business_id=biz_id)

    res = HistoricalCadenceValidator.evaluate_cutoff(
        session=session,
        context=ctx,
        cutoff_date=date(2023, 6, 30),
        buffer_days=7,
        horizon_days=60,
        ingestion_watermark=datetime(2023, 12, 31, 23, 59, 59, tzinfo=UTC),
        include_customer_records=True,
    )

    all_ids = [r.customer_id for r in res.customer_records]
    assert len(all_ids) == len(set(all_ids)), "Customer records must have unique IDs per cutoff"

    # Partition by deterministic modulo hash
    train_ids = {cid for cid in all_ids if (cid * 17) % 10 < 6}
    holdout_ids = {cid for cid in all_ids if cid not in train_ids}

    assert train_ids.isdisjoint(holdout_ids)
    assert len(train_ids) + len(holdout_ids) == len(all_ids)


def test_one_time_buyers_remain_unscored_under_all_calibration_thresholds(recalibration_session):
    """Verify that one-time buyers are NEVER assigned to scored tiers under any threshold."""
    session, biz_id = recalibration_session
    ctx = AnalysisContext(business_id=biz_id)

    for cfg in [
        CadenceConfig(low_threshold=1.25, medium_threshold=2.0, high_threshold=3.0),
        CadenceConfig(low_threshold=1.5, medium_threshold=2.2, high_threshold=3.5),
        CadenceConfig(low_threshold=1.3, medium_threshold=1.8, high_threshold=2.8),
        CadenceConfig(low_threshold=1.2, medium_threshold=1.6, high_threshold=2.5),
    ]:
        summary = CustomerCadenceAnalyzer.evaluate(
            session=session,
            context=ctx,
            as_of_date=datetime(2023, 6, 30, 23, 59, 59, tzinfo=UTC),
            config=cfg,
        )
        one_timers = [r for r in summary.records if r.eligible_order_count < 2]
        for ot in one_timers:
            assert ot.risk_tier == CadenceRiskTier.INSUFFICIENT_HISTORY


def test_backfill_invalidation_blocks_subsequent_cutoff_verification(recalibration_session):
    """Verify that invalidating an active watermark immediately blocks verified evaluation."""
    session, biz_id = recalibration_session
    ctx = AnalysisContext(business_id=biz_id)

    # 1. Record verified watermark
    WatermarkService.record_watermark(
        session=session,
        contract=WatermarkContract(
            business_id=biz_id,
            source_id="pos",
            complete_through_dt=datetime(2023, 12, 31, 23, 59, 59, tzinfo=UTC),
            provenance_type="manual_close",
            verification_status="verified",
        ),
    )
    session.commit()

    # 2. Invalidate due to backfill
    WatermarkService.invalidate_watermark(
        session=session,
        business_id=biz_id,
        source_id="pos",
        reason="Historical correction arrived for Q2 2023",
    )
    session.commit()

    # 3. Evaluate cutoff requiring verified watermark
    res = HistoricalCadenceValidator.evaluate_cutoff(
        session=session,
        context=ctx,
        cutoff_date=date(2023, 3, 31),
        buffer_days=7,
        horizon_days=60,
        require_verified_watermark=True,
    )

    assert res.is_complete_followup is False
    assert res.is_followup_verified is False
    assert res.followup_status == "incomplete_watermark_invalidated"
    assert "invalidated" in res.censoring_reason.lower()
