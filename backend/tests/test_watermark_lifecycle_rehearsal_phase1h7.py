"""
NEXUS Phase 1H.7 — Isolated Watermark Lifecycle Integration Rehearsal.

Validates end-to-end watermark registration and downstream safety behavior
using isolated test fixtures without asserting that Apex Specialty Commerce's
CSV data is complete or registering any watermark for Apex.

Scenarios tested:
1. Register a valid synthetic watermark for an isolated fixture and verify diagnostic/test state.
2. Reject invalid or unsupported provenance and malformed timestamps.
3. Verify idempotent registration and supersession behavior.
4. Verify completeness regression protection and backfill invalidation.
5. Verify stale, provisional, or missing watermark behavior.
6. Verify multi-source completeness uses the correct conservative boundary.
7. Confirm the synthetic fixture's downstream safety result matches the intended test contract.
8. Confirm tenant isolation: Apex remains untouched and unwatermarked.
"""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from app.analytics.customer.cadence import (
    CadenceConfig,
    CadenceRiskTier,
    CustomerCadenceAnalyzer,
)
from app.analytics.customer.safety import (
    ActionExecutionStatus,
    CadenceActionGate,
    CadenceEligibilityStatus,
    CadenceSafetyGate,
    SafetyReasonCode,
    SeasonalContextType,
)
from app.models.customer import Customer
from app.models.sale import Sale
from app.models.tenant import Business, IngestionJob, Organization
from app.models.watermark import TenantIngestionWatermark
from app.services.watermark_service import (
    ALLOWED_PROVENANCE_TYPES,
    ALLOWED_VERIFICATION_STATUSES,
    WatermarkContract,
    WatermarkService,
)


def _create_isolated_rehearsal_tenant(
    session: Session, name_suffix: str = "rehearsal", industry: str = "Specialty Retail"
) -> Business:
    """Create an isolated test organization and business."""
    uid = uuid4().hex[:8]
    org = Organization(
        id=f"org-rh-{name_suffix}-{uid}",
        name=f"Rehearsal Org {name_suffix} {uid}",
        slug=f"org-rh-{name_suffix}-{uid}",
    )
    biz = Business(
        id=f"biz-rh-{name_suffix}-{uid}",
        organization_id=org.id,
        name=f"Rehearsal Fixture {name_suffix} {uid}",
        industry=industry,
        country="US",
        currency="USD",
        status="active",
    )
    session.add_all([org, biz])
    session.commit()
    return biz


def _seed_rehearsal_sales_cohort(
    session: Session,
    business_id: str,
    repeat_buyers_count: int = 35,
    one_time_buyers_count: int = 10,
    base_date: datetime | None = None,
    start_id: int = 50000,
):
    """Seed synthetic customer purchase cohort for safety gate testing."""
    ref = base_date or datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
    cust_id_counter = start_id

    # Repeat buyers (2 completed purchases separated by 30 days)
    for i in range(repeat_buyers_count):
        cust_id_counter += 1
        c = Customer(
            id=cust_id_counter,
            business_id=business_id,
            customer_code=f"REP-RH-{i:04d}",
            name=f"Rehearsal Repeat Buyer {i}",
            email=f"rep_rh_{i}@example.com",
            customer_segment="Standard",
            city="Seattle",
            acquisition_date=(ref - timedelta(days=90)).date(),
        )
        session.add(c)
        s1 = Sale(
            id=cust_id_counter * 10 + 1,
            business_id=business_id,
            customer_id=c.id,
            transaction_number=f"TX-RH-{c.id}-1",
            transaction_date=ref - timedelta(days=60),
            subtotal=100.0,
            discount_amount=0.0,
            tax_amount=0.0,
            total_amount=100.0,
            status="completed",
        )
        s2 = Sale(
            id=cust_id_counter * 10 + 2,
            business_id=business_id,
            customer_id=c.id,
            transaction_number=f"TX-RH-{c.id}-2",
            transaction_date=ref - timedelta(days=20),
            subtotal=120.0,
            discount_amount=0.0,
            tax_amount=0.0,
            total_amount=120.0,
            status="completed",
        )
        session.add_all([s1, s2])

    # One-time buyers
    for j in range(one_time_buyers_count):
        cust_id_counter += 1
        c = Customer(
            id=cust_id_counter,
            business_id=business_id,
            customer_code=f"ONE-RH-{j:04d}",
            name=f"Rehearsal One Time Buyer {j}",
            email=f"one_rh_{j}@example.com",
            customer_segment="Standard",
            city="Portland",
            acquisition_date=(ref - timedelta(days=45)).date(),
        )
        session.add(c)
        s = Sale(
            id=cust_id_counter * 10 + 1,
            business_id=business_id,
            customer_id=c.id,
            transaction_number=f"TX-RH-{c.id}-1",
            transaction_date=ref - timedelta(days=30),
            subtotal=65.0,
            discount_amount=0.0,
            tax_amount=0.0,
            total_amount=65.0,
            status="completed",
        )
        session.add(s)

    session.commit()


# ==============================================================================
# Scenario 1: Valid Synthetic Watermark Registration and Diagnostic State
# ==============================================================================

def test_scenario1_valid_synthetic_watermark_registration(db_session: Session):
    """Scenario 1: Register a valid synthetic watermark for an isolated fixture and verify diagnostic/test state."""
    biz = _create_isolated_rehearsal_tenant(db_session, "scen1")
    target_dt = datetime(2026, 6, 30, 23, 59, 59, tzinfo=UTC)

    contract = WatermarkContract(
        business_id=biz.id,
        source_id="default",
        complete_through_dt=target_dt,
        provenance_type="synthetic_fixture",
        verification_status="verified",
        metadata_json={
            "rehearsal_phase": "1H.7",
            "fixture_label": "synthetic_isolated_test",
            "is_real_source_attestation": False,
        },
    )
    wm = WatermarkService.record_watermark(db_session, contract)
    db_session.commit()

    assert wm.id is not None
    assert wm.business_id == biz.id
    assert wm.source_id == "default"
    assert wm.complete_through_utc == target_dt
    assert wm.provenance_type == "synthetic_fixture"
    assert wm.verification_status == "verified"
    assert wm.is_active is True
    assert wm.metadata_json.get("is_real_source_attestation") is False

    # Verify effective watermark calculation
    eff = WatermarkService.get_effective_tenant_watermark(db_session, biz.id, max_staleness_days=None)
    assert eff.is_verified is True
    assert eff.status == "verified_complete"
    assert eff.effective_complete_through_dt == target_dt
    assert eff.earliest_source_id == "default"
    assert eff.in_flight_or_failed_jobs_count == 0
    assert len(eff.blocking_reasons) == 0


# ==============================================================================
# Scenario 2: Rejection of Invalid Provenance, Statuses, and Malformed Timestamps
# ==============================================================================

def test_scenario2_rejection_of_invalid_provenance_and_timestamps(db_session: Session):
    """Scenario 2: Reject invalid/unsupported provenance, bad statuses, and malformed timestamps."""
    biz = _create_isolated_rehearsal_tenant(db_session, "scen2")
    valid_dt = datetime(2026, 6, 30, 12, 0, tzinfo=UTC)

    # 1. Invalid provenance types
    for bad_prov in ["guessed_timestamp", "csv_upload", "max_transaction_date", "heuristic_guess", ""]:
        with pytest.raises(ValueError, match="Invalid provenance_type"):
            WatermarkContract(
                business_id=biz.id,
                source_id="default",
                complete_through_dt=valid_dt,
                provenance_type=bad_prov,
                verification_status="verified",
            )

    # 2. Invalid verification statuses
    for bad_status in ["half_verified", "in_progress", "unknown", "approved"]:
        with pytest.raises(ValueError, match="Invalid verification_status"):
            WatermarkContract(
                business_id=biz.id,
                source_id="default",
                complete_through_dt=valid_dt,
                provenance_type="synthetic_fixture",
                verification_status=bad_status,
            )

    # 3. Timestamps before year 2000
    with pytest.raises(ValueError, match="cannot be before year 2000"):
        WatermarkContract(
            business_id=biz.id,
            source_id="default",
            complete_through_dt=datetime(1999, 12, 31, 23, 59, 59, tzinfo=UTC),
            provenance_type="synthetic_fixture",
            verification_status="verified",
        )

    # 4. Future timestamps exceeding clock skew
    future_dt = datetime.now(UTC) + timedelta(days=5)
    with pytest.raises(ValueError, match="cannot be in the future"):
        WatermarkContract(
            business_id=biz.id,
            source_id="default",
            complete_through_dt=future_dt,
            provenance_type="synthetic_fixture",
            verification_status="verified",
        )

    # 5. Empty or whitespace source_id
    with pytest.raises(ValueError, match="source_id cannot be empty or whitespace only"):
        WatermarkContract(
            business_id=biz.id,
            source_id="   ",
            complete_through_dt=valid_dt,
            provenance_type="synthetic_fixture",
            verification_status="verified",
        )


# ==============================================================================
# Scenario 3: Idempotent Registration and Supersession Behavior
# ==============================================================================

def test_scenario3_idempotency_and_supersession(db_session: Session):
    """Scenario 3: Verify idempotent registration and supersession behavior."""
    biz = _create_isolated_rehearsal_tenant(db_session, "scen3")
    t1 = datetime(2026, 5, 31, 23, 59, 59, tzinfo=UTC)
    t2 = datetime(2026, 6, 30, 23, 59, 59, tzinfo=UTC)

    contract1 = WatermarkContract(
        business_id=biz.id,
        source_id="pos",
        complete_through_dt=t1,
        provenance_type="synthetic_fixture",
        verification_status="verified",
        metadata_json={"batch": "BATCH-01"},
    )

    # First record
    wm1 = WatermarkService.record_watermark(db_session, contract1)
    db_session.commit()
    assert wm1.is_active is True

    # Idempotent re-record: identical contract returns existing object without new row
    wm1_idempotent = WatermarkService.record_watermark(db_session, contract1)
    assert wm1_idempotent.id == wm1.id

    active_rows = db_session.query(TenantIngestionWatermark).filter_by(
        business_id=biz.id, source_id="pos", is_active=True
    ).all()
    assert len(active_rows) == 1

    # Supersession: Advance boundary to t2
    contract2 = WatermarkContract(
        business_id=biz.id,
        source_id="pos",
        complete_through_dt=t2,
        provenance_type="synthetic_fixture",
        verification_status="verified",
        metadata_json={"batch": "BATCH-02"},
    )
    wm2 = WatermarkService.record_watermark(db_session, contract2)
    db_session.commit()

    assert wm2.id != wm1.id
    assert wm2.is_active is True
    assert wm2.complete_through_utc == t2

    # Old watermark is deactivated
    db_session.refresh(wm1)
    assert wm1.is_active is False

    # Audit history contains both records
    history = WatermarkService.get_watermark_history(db_session, biz.id, source_id="pos")
    assert len(history) == 2
    assert history[0].id == wm2.id  # newest first
    assert history[1].id == wm1.id


# ==============================================================================
# Scenario 4: Completeness Regression Protection and Backfill Invalidation
# ==============================================================================

def test_scenario4_regression_protection_and_backfill_invalidation(db_session: Session):
    """Scenario 4: Verify completeness regression protection and backfill invalidation."""
    biz = _create_isolated_rehearsal_tenant(db_session, "scen4")
    t_certified = datetime(2026, 6, 30, 23, 59, 59, tzinfo=UTC)
    t_earlier = datetime(2026, 5, 15, 12, 0, 0, tzinfo=UTC)

    # Establish certified watermark through 2026-06-30
    wm = WatermarkService.record_watermark(
        db_session,
        WatermarkContract(
            business_id=biz.id,
            source_id="default",
            complete_through_dt=t_certified,
            provenance_type="synthetic_fixture",
            verification_status="verified",
        ),
    )
    db_session.commit()
    assert wm.is_active is True

    # 1. Backward regression is blocked when allow_regression=False
    with pytest.raises(ValueError, match="Cannot advance verified watermark backward in time"):
        WatermarkService.record_watermark(
            db_session,
            WatermarkContract(
                business_id=biz.id,
                source_id="default",
                complete_through_dt=t_earlier,
                provenance_type="synthetic_fixture",
                verification_status="verified",
            ),
            allow_regression=False,
        )

    # 2. Backfill detection automatically invalidates the active watermark
    late_arriving_date = datetime(2026, 6, 10, 8, 30, tzinfo=UTC)
    invalidated = WatermarkService.detect_backfill_and_handle(
        session=db_session,
        business_id=biz.id,
        source_id="default",
        transaction_dates=[late_arriving_date],
        job_id="job-late-arrival-001",
    )
    db_session.commit()

    assert invalidated is True
    db_session.refresh(wm)
    assert wm.verification_status == "invalidated"
    assert "Backfill detected" in wm.invalidation_reason
    assert "job: job-late-arrival-001" in wm.invalidation_reason

    # Downstream effective watermark is now invalidated
    eff = WatermarkService.get_effective_tenant_watermark(db_session, biz.id)
    assert eff.is_verified is False
    assert eff.status == "invalidated"


# ==============================================================================
# Scenario 5: Stale, Provisional, or Missing Watermark Behavior
# ==============================================================================

def test_scenario5_missing_stale_and_provisional_watermarks(db_session: Session):
    """Scenario 5: Verify stale, provisional, or missing watermark behavior."""
    # 1. Missing watermark
    biz_missing = _create_isolated_rehearsal_tenant(db_session, "scen5-missing")
    eff_missing = WatermarkService.get_effective_tenant_watermark(db_session, biz_missing.id)
    assert eff_missing.is_verified is False
    assert eff_missing.status == "unverified_missing"

    verdict_missing = CadenceSafetyGate.evaluate_tenant_safety(db_session, biz_missing.id)
    assert verdict_missing.eligibility_status == CadenceEligibilityStatus.DIAGNOSTIC_ONLY
    assert verdict_missing.reason_code == SafetyReasonCode.MISSING_WATERMARK
    assert verdict_missing.is_actionable is False

    # 2. Stale watermark (> 90 days old)
    biz_stale = _create_isolated_rehearsal_tenant(db_session, "scen5-stale")
    stale_dt = datetime.now(UTC) - timedelta(days=120)
    WatermarkService.record_watermark(
        db_session,
        WatermarkContract(
            business_id=biz_stale.id,
            source_id="default",
            complete_through_dt=stale_dt,
            provenance_type="synthetic_fixture",
            verification_status="verified",
        ),
    )
    db_session.commit()

    eff_stale = WatermarkService.get_effective_tenant_watermark(
        db_session, biz_stale.id, max_staleness_days=90
    )
    assert eff_stale.is_stale is True
    assert "exceeding max staleness" in eff_stale.stale_warning

    verdict_stale = CadenceSafetyGate.evaluate_tenant_safety(
        db_session, biz_stale.id, as_of_date=stale_dt, max_staleness_days=90
    )
    assert verdict_stale.eligibility_status == CadenceEligibilityStatus.DIAGNOSTIC_ONLY
    assert verdict_stale.reason_code == SafetyReasonCode.STALE_WATERMARK
    assert verdict_stale.is_actionable is False

    # 3. Provisional watermark (unpromoted)
    biz_prov = _create_isolated_rehearsal_tenant(db_session, "scen5-prov")
    WatermarkService.record_watermark(
        db_session,
        WatermarkContract(
            business_id=biz_prov.id,
            source_id="default",
            complete_through_dt=datetime(2026, 6, 30, tzinfo=UTC),
            provenance_type="synthetic_fixture",
            verification_status="provisional",
        ),
    )
    db_session.commit()

    eff_prov = WatermarkService.get_effective_tenant_watermark(db_session, biz_prov.id, max_staleness_days=None)
    assert eff_prov.is_verified is False
    assert eff_prov.status == "incomplete_watermark_gap"

    verdict_prov = CadenceSafetyGate.evaluate_tenant_safety(db_session, biz_prov.id, max_staleness_days=None)
    assert verdict_prov.eligibility_status == CadenceEligibilityStatus.DIAGNOSTIC_ONLY
    assert verdict_prov.reason_code == SafetyReasonCode.PROVISIONAL_WATERMARK
    assert verdict_prov.is_actionable is False


# ==============================================================================
# Scenario 6: Multi-Source Conservative Minimum Boundary
# ==============================================================================

def test_scenario6_multi_source_conservative_boundary(db_session: Session):
    """Scenario 6: Verify multi-source completeness uses the correct conservative boundary."""
    biz = _create_isolated_rehearsal_tenant(db_session, "scen6")
    t_pos = datetime(2026, 6, 30, 23, 59, 59, tzinfo=UTC)
    t_ecom = datetime(2026, 5, 31, 23, 59, 59, tzinfo=UTC)

    # Source 1: POS complete through June 30
    WatermarkService.record_watermark(
        db_session,
        WatermarkContract(
            business_id=biz.id,
            source_id="pos",
            complete_through_dt=t_pos,
            provenance_type="synthetic_fixture",
            verification_status="verified",
        ),
    )
    # Source 2: eCommerce complete through May 31
    WatermarkService.record_watermark(
        db_session,
        WatermarkContract(
            business_id=biz.id,
            source_id="ecommerce",
            complete_through_dt=t_ecom,
            provenance_type="synthetic_fixture",
            verification_status="verified",
        ),
    )
    db_session.commit()

    # Effective watermark must take the minimum (May 31)
    eff = WatermarkService.get_effective_tenant_watermark(
        db_session, biz.id, required_sources=["pos", "ecommerce"], max_staleness_days=None
    )
    assert eff.is_verified is True
    assert eff.status == "verified_complete"
    assert eff.effective_complete_through_dt == t_ecom
    assert eff.earliest_source_id == "ecommerce"

    # If an additional required source is missing, verification fails with incomplete_watermark_gap
    eff_missing_source = WatermarkService.get_effective_tenant_watermark(
        db_session, biz.id, required_sources=["pos", "ecommerce", "wholesale"], max_staleness_days=None
    )
    assert eff_missing_source.is_verified is False
    assert eff_missing_source.status == "incomplete_watermark_gap"
    assert eff_missing_source.unverified_sources == ["wholesale"]


# ==============================================================================
# Scenario 7: Synthetic Fixture Downstream Safety Result & Action Gating
# ==============================================================================

def test_scenario7_downstream_safety_contract_and_action_gate(db_session: Session):
    """Scenario 7: Confirm synthetic fixture downstream safety result matches the intended test contract."""
    biz = _create_isolated_rehearsal_tenant(db_session, "scen7")
    _seed_rehearsal_sales_cohort(
        db_session,
        biz.id,
        repeat_buyers_count=35,
        one_time_buyers_count=10,
        base_date=datetime(2026, 6, 1, 12, 0, tzinfo=UTC),
    )

    t_certified = datetime(2026, 6, 30, 23, 59, 59, tzinfo=UTC)
    WatermarkService.record_watermark(
        db_session,
        WatermarkContract(
            business_id=biz.id,
            source_id="default",
            complete_through_dt=t_certified,
            provenance_type="synthetic_fixture",
            verification_status="verified",
            metadata_json={"rehearsal_phase": "1H.7"},
        ),
    )
    db_session.commit()

    # 7A: Within certified boundary -> ACTIONABLE
    cutoff_within = datetime(2026, 6, 15, 12, 0, tzinfo=UTC)
    verdict_within = CadenceSafetyGate.evaluate_tenant_safety(
        session=db_session,
        business_id=biz.id,
        as_of_date=cutoff_within,
        max_staleness_days=None,
    )
    assert verdict_within.eligibility_status == CadenceEligibilityStatus.ACTIONABLE
    assert verdict_within.is_actionable is True
    assert verdict_within.reason_code == SafetyReasonCode.VERIFIED_ACTIONABLE
    assert verdict_within.eligible_repeat_buyers_count == 35

    # 7B: Cutoff exceeds watermark boundary -> DIAGNOSTIC_ONLY (CUTOFF_EXCEEDS_WATERMARK)
    cutoff_exceeding = datetime(2026, 7, 15, 12, 0, tzinfo=UTC)
    verdict_exceeding = CadenceSafetyGate.evaluate_tenant_safety(
        session=db_session,
        business_id=biz.id,
        as_of_date=cutoff_exceeding,
        max_staleness_days=None,
    )
    assert verdict_exceeding.eligibility_status == CadenceEligibilityStatus.DIAGNOSTIC_ONLY
    assert verdict_exceeding.is_actionable is False
    assert verdict_exceeding.reason_code == SafetyReasonCode.CUTOFF_EXCEEDS_WATERMARK

    # 7C: Action gating enforces Human-Review-Only policy even when ACTIONABLE
    auto_action = CadenceActionGate.evaluate_action_eligibility(
        session=db_session,
        business_id=biz.id,
        action_type="send_retention_discount",
        reviewer_id=None,
        is_automated_caller=True,
    )
    assert auto_action.is_allowed is False
    assert auto_action.status == ActionExecutionStatus.BLOCKED_AUTOMATION_PROHIBITED
    assert "automated" in auto_action.reason.lower()


# ==============================================================================
# Scenario 8: Tenant Isolation Invariant (Apex Remains Untouched)
# ==============================================================================

def test_scenario8_apex_isolation_invariant(db_session: Session):
    """Scenario 8: Confirm tenant isolation: Apex remains untouched and unwatermarked."""
    # Ensure any querying against an unwatermarked tenant returns missing watermark
    apex_id = "ab044b1a-835a-4a38-bf45-62fe38624151"
    active_wms = WatermarkService.get_active_watermarks(db_session, apex_id)
    assert len(active_wms) == 0

    eff = WatermarkService.get_effective_tenant_watermark(db_session, apex_id)
    assert eff.is_verified is False
    assert eff.status == "unverified_missing"
