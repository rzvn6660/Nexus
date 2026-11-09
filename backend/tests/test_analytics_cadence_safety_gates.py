"""
Unit and integration tests for NEXUS Phase 1H.2 — Controlled Pilot Safety Gates.

Covers:
1. Missing watermark blocks actionable risk presentation.
2. Provisional, stale, invalidated, and incomplete watermarks block certification.
3. Multiple required sources use the conservative effective minimum boundary.
4. Evaluation cutoff beyond complete-through boundary cannot be presented as verified.
5. One-time and insufficient-history customers remain strictly unscored.
6. Tenant isolation is preserved.
7. Seasonal warnings appear for applicable retail contexts.
8. Unknown seasonal context produces cautious disclosure without false customer classification.
9. Risk displays and action paths enforce human-review-only policy.
10. AnalyticsService integration and evidence builder generation.
"""

from datetime import UTC, date, datetime, timedelta
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.analytics.core.context import AnalysisContext
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
from app.analytics.service import AnalyticsService
from app.models.base import Base
from app.models.customer import Customer
from app.models.history import DecisionRecord
from app.models.sale import Sale
from app.models.tenant import Business, IngestionJob, Organization
from app.models.watermark import TenantIngestionWatermark
from app.services.watermark_service import WatermarkContract, WatermarkService


@pytest.fixture
def db_session():
    """Create an in-memory SQLite database session for unit testing."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


def _seed_tenant(session: Session, business_id: str, name: str, industry: str = "Specialty Retail") -> Business:
    """Helper to seed an organization and business."""
    org = Organization(id=f"org-{business_id}", name=f"Org {name}", slug=f"org-{business_id}")
    session.add(org)
    biz = Business(
        id=business_id,
        organization_id=org.id,
        name=name,
        industry=industry,
        country="US",
        currency="USD",
        status="active",
    )
    session.add(biz)
    session.commit()
    return biz


def _seed_customers_and_sales(
    session: Session,
    business_id: str,
    repeat_buyers_count: int = 35,
    one_time_buyers_count: int = 10,
    base_date: datetime | None = None,
    start_id: int = 1000,
):
    """Seed synthetic customers and completed transactions."""
    ref = base_date or (datetime.now(UTC) - timedelta(days=10))
    cust_id_counter = start_id

    # Repeat buyers (2 purchases separated by 30 days)
    for i in range(repeat_buyers_count):
        cust_id_counter += 1
        c = Customer(
            id=cust_id_counter,
            business_id=business_id,
            customer_code=f"REP-{i:04d}",
            name=f"Repeat Buyer {i}",
            email=f"rep_{i}@example.com",
            customer_segment="Standard",
            city="Seattle",
            acquisition_date=(ref - timedelta(days=90)).date(),
        )
        session.add(c)
        # Tx 1
        s1 = Sale(
            id=cust_id_counter * 10 + 1,
            business_id=business_id,
            customer_id=c.id,
            transaction_number=f"TX-{c.id}-1",
            transaction_date=ref - timedelta(days=60),
            subtotal=100.0,
            discount_amount=0.0,
            tax_amount=0.0,
            total_amount=100.0,
            status="completed",
        )
        # Tx 2
        s2 = Sale(
            id=cust_id_counter * 10 + 2,
            business_id=business_id,
            customer_id=c.id,
            transaction_number=f"TX-{c.id}-2",
            transaction_date=ref - timedelta(days=30),
            subtotal=100.0,
            discount_amount=0.0,
            tax_amount=0.0,
            total_amount=100.0,
            status="completed",
        )
        session.add_all([s1, s2])

    # One-time buyers (exactly 1 purchase)
    for j in range(one_time_buyers_count):
        cust_id_counter += 1
        c = Customer(
            id=cust_id_counter,
            business_id=business_id,
            customer_code=f"ONE-{j:04d}",
            name=f"One Time Buyer {j}",
            email=f"one_{j}@example.com",
            customer_segment="Standard",
            city="Portland",
            acquisition_date=(ref - timedelta(days=45)).date(),
        )
        session.add(c)
        s = Sale(
            id=cust_id_counter * 10 + 1,
            business_id=business_id,
            customer_id=c.id,
            transaction_number=f"TX-{c.id}-1",
            transaction_date=ref - timedelta(days=45),
            subtotal=50.0,
            discount_amount=0.0,
            tax_amount=0.0,
            total_amount=50.0,
            status="completed",
        )
        session.add(s)

    session.commit()


# =========================================================================
# 1. Missing Watermark Blocks Actionable Risk Presentation
# =========================================================================

def test_missing_watermark_blocks_actionable_risk(db_session):
    biz = _seed_tenant(db_session, "biz-no-wm", "No Watermark Retail", industry="Retail")
    _seed_customers_and_sales(db_session, biz.id, repeat_buyers_count=35)

    verdict = CadenceSafetyGate.evaluate_tenant_safety(
        session=db_session,
        business_id=biz.id,
        as_of_date=datetime(2026, 6, 1, tzinfo=UTC),
    )

    assert verdict.eligibility_status == CadenceEligibilityStatus.DIAGNOSTIC_ONLY
    assert verdict.is_actionable is False
    assert verdict.reason_code == SafetyReasonCode.MISSING_WATERMARK
    assert "No authoritative ingestion watermark is registered" in verdict.explanation
    assert verdict.non_actionable_notice is not None
    assert "NON-ACTIONABLE DIAGNOSTIC TELEMETRY" in verdict.non_actionable_notice


# =========================================================================
# 2. Provisional, Stale, Invalidated, and Incomplete Watermarks Block Certification
# =========================================================================

def test_provisional_watermark_blocks_certification(db_session):
    biz = _seed_tenant(db_session, "biz-provisional", "Provisional Retail")
    _seed_customers_and_sales(db_session, biz.id, repeat_buyers_count=35)

    WatermarkService.record_watermark(
        db_session,
        WatermarkContract(
            business_id=biz.id,
            source_id="default",
            complete_through_dt=datetime(2026, 6, 1, tzinfo=UTC),
            verification_status="provisional",
        ),
    )
    db_session.commit()

    verdict = CadenceSafetyGate.evaluate_tenant_safety(
        session=db_session,
        business_id=biz.id,
        as_of_date=datetime(2026, 6, 1, tzinfo=UTC),
    )

    assert verdict.is_actionable is False
    assert verdict.eligibility_status == CadenceEligibilityStatus.DIAGNOSTIC_ONLY
    assert verdict.reason_code == SafetyReasonCode.PROVISIONAL_WATERMARK


def test_invalidated_watermark_blocks_certification(db_session):
    biz = _seed_tenant(db_session, "biz-invalidated", "Invalidated Retail")
    _seed_customers_and_sales(db_session, biz.id, repeat_buyers_count=35)

    WatermarkService.record_watermark(
        db_session,
        WatermarkContract(
            business_id=biz.id,
            source_id="default",
            complete_through_dt=datetime(2026, 6, 1, tzinfo=UTC),
            verification_status="verified",
        ),
    )
    db_session.commit()

    # Invalidate watermark
    WatermarkService.invalidate_watermark(db_session, business_id=biz.id, reason="Backfill detected")
    db_session.commit()

    verdict = CadenceSafetyGate.evaluate_tenant_safety(
        session=db_session,
        business_id=biz.id,
        as_of_date=datetime(2026, 6, 1, tzinfo=UTC),
    )

    assert verdict.is_actionable is False
    assert verdict.eligibility_status == CadenceEligibilityStatus.DIAGNOSTIC_ONLY
    assert verdict.reason_code == SafetyReasonCode.INVALIDATED_WATERMARK


def test_stale_watermark_blocks_certification(db_session):
    biz = _seed_tenant(db_session, "biz-stale", "Stale Retail")
    _seed_customers_and_sales(db_session, biz.id, repeat_buyers_count=35)

    # 150 days in the past relative to now
    stale_date = datetime.now(UTC) - timedelta(days=150)
    WatermarkService.record_watermark(
        db_session,
        WatermarkContract(
            business_id=biz.id,
            source_id="default",
            complete_through_dt=stale_date,
            verification_status="verified",
        ),
    )
    db_session.commit()

    verdict = CadenceSafetyGate.evaluate_tenant_safety(
        session=db_session,
        business_id=biz.id,
        as_of_date=stale_date,
        max_staleness_days=90,
    )

    assert verdict.is_actionable is False
    assert verdict.reason_code == SafetyReasonCode.STALE_WATERMARK


def test_in_flight_job_blocks_certification(db_session):
    biz = _seed_tenant(db_session, "biz-inflight", "In-Flight Job Retail")
    _seed_customers_and_sales(db_session, biz.id, repeat_buyers_count=35)

    WatermarkService.record_watermark(
        db_session,
        WatermarkContract(
            business_id=biz.id,
            source_id="default",
            complete_through_dt=datetime(2026, 6, 1, tzinfo=UTC),
            verification_status="verified",
        ),
    )
    # Add pending ingestion job
    job = IngestionJob(
        id="job-pending-1",
        organization_id=biz.organization_id,
        business_id=biz.id,
        dataset_id="ds-pending-1",
        status="PROCESSING",
        created_at=datetime.now(UTC),
    )
    db_session.add(job)
    db_session.commit()

    verdict = CadenceSafetyGate.evaluate_tenant_safety(
        session=db_session,
        business_id=biz.id,
        as_of_date=datetime(2026, 6, 1, tzinfo=UTC),
    )

    assert verdict.is_actionable is False
    assert verdict.reason_code == SafetyReasonCode.INCOMPLETE_IN_FLIGHT_JOBS


# =========================================================================
# 3. Multiple Required Sources Use Conservative Effective Boundary
# =========================================================================

def test_multiple_sources_conservative_boundary(db_session):
    biz = _seed_tenant(db_session, "biz-multi-src", "Multi-Source Retail")
    _seed_customers_and_sales(db_session, biz.id, repeat_buyers_count=35)

    recent_now = datetime.now(UTC)
    pos_dt = recent_now - timedelta(days=5)
    ecom_dt = recent_now - timedelta(days=15)

    # POS verified through 5 days ago
    WatermarkService.record_watermark(
        db_session,
        WatermarkContract(
            business_id=biz.id,
            source_id="pos",
            complete_through_dt=pos_dt,
            verification_status="verified",
        ),
    )
    # Ecommerce verified through 15 days ago
    WatermarkService.record_watermark(
        db_session,
        WatermarkContract(
            business_id=biz.id,
            source_id="ecommerce",
            complete_through_dt=ecom_dt,
            verification_status="verified",
        ),
    )
    db_session.commit()

    # Evaluation at 16 days ago: within conservative boundary (15 days ago) -> ACTIONABLE
    verdict_valid = CadenceSafetyGate.evaluate_tenant_safety(
        session=db_session,
        business_id=biz.id,
        as_of_date=recent_now - timedelta(days=16),
        required_sources=["pos", "ecommerce"],
    )
    assert verdict_valid.is_actionable is True
    assert verdict_valid.reason_code == SafetyReasonCode.VERIFIED_ACTIONABLE

    # Evaluation at 10 days ago: exceeds ecommerce boundary (15 days ago) even though pos is 5 days ago -> DIAGNOSTIC_ONLY
    verdict_exceeded = CadenceSafetyGate.evaluate_tenant_safety(
        session=db_session,
        business_id=biz.id,
        as_of_date=recent_now - timedelta(days=10),
        required_sources=["pos", "ecommerce"],
    )
    assert verdict_exceeded.is_actionable is False
    assert verdict_exceeded.reason_code == SafetyReasonCode.CUTOFF_EXCEEDS_WATERMARK


# =========================================================================
# 4. Cutoff Beyond Complete-Through Boundary Cannot Be Presented as Verified
# =========================================================================

def test_cutoff_beyond_boundary_blocks_actionable(db_session):
    biz = _seed_tenant(db_session, "biz-cutoff-check", "Boundary Test Retail")
    _seed_customers_and_sales(db_session, biz.id, repeat_buyers_count=35)

    recent_now = datetime.now(UTC)
    wm_dt = recent_now - timedelta(days=10)

    WatermarkService.record_watermark(
        db_session,
        WatermarkContract(
            business_id=biz.id,
            source_id="default",
            complete_through_dt=wm_dt,
            verification_status="verified",
        ),
    )
    db_session.commit()

    # Cutoff 5 days after watermark (5 days ago)
    verdict = CadenceSafetyGate.evaluate_tenant_safety(
        session=db_session,
        business_id=biz.id,
        as_of_date=recent_now - timedelta(days=5),
    )

    assert verdict.is_actionable is False
    assert verdict.eligibility_status == CadenceEligibilityStatus.DIAGNOSTIC_ONLY
    assert verdict.reason_code == SafetyReasonCode.CUTOFF_EXCEEDS_WATERMARK
    assert "extends beyond the certified complete-through boundary" in verdict.explanation


# =========================================================================
# 5. One-Time and Insufficient-History Customers Remain Strictly Unscored
# =========================================================================

def test_one_time_buyers_remain_unscored(db_session):
    biz = _seed_tenant(db_session, "biz-unscored", "Unscored Safety Retail")
    _seed_customers_and_sales(db_session, biz.id, repeat_buyers_count=35, one_time_buyers_count=10)

    recent_now = datetime.now(UTC)
    wm_dt = recent_now - timedelta(days=5)

    WatermarkService.record_watermark(
        db_session,
        WatermarkContract(
            business_id=biz.id,
            source_id="default",
            complete_through_dt=wm_dt,
            verification_status="verified",
        ),
    )
    db_session.commit()

    # Even with use_segment_fallback=True, one-time buyers must remain INSUFFICIENT_HISTORY
    cfg = CadenceConfig(use_segment_fallback=True)
    summary, verdict = CadenceSafetyGate.evaluate_customer_cadence_with_safety(
        session=db_session,
        business_id=biz.id,
        as_of_date=wm_dt,
        config=cfg,
    )

    one_time_records = [r for r in summary.records if not r.is_repeat_buyer]
    assert len(one_time_records) == 10
    for r in one_time_records:
        assert r.risk_tier == CadenceRiskTier.INSUFFICIENT_HISTORY
        assert r.cadence_ratio is None
        assert r.cadence_source in {"insufficient_history", "no_purchases"}


# =========================================================================
# 6. Tenant Isolation is Preserved
# =========================================================================

def test_tenant_isolation_in_safety_gates(db_session):
    biz_a = _seed_tenant(db_session, "biz-isolated-a", "Tenant A", industry="Retail")
    biz_b = _seed_tenant(db_session, "biz-isolated-b", "Tenant B", industry="Retail")
    _seed_customers_and_sales(db_session, biz_a.id, repeat_buyers_count=35, start_id=1000)
    _seed_customers_and_sales(db_session, biz_b.id, repeat_buyers_count=5, start_id=5000)  # below 30

    recent_now = datetime.now(UTC)
    wm_dt = recent_now - timedelta(days=5)

    # Tenant A has verified watermark
    WatermarkService.record_watermark(
        db_session,
        WatermarkContract(
            business_id=biz_a.id,
            source_id="default",
            complete_through_dt=wm_dt,
            verification_status="verified",
        ),
    )
    db_session.commit()

    verdict_a = CadenceSafetyGate.evaluate_tenant_safety(
        session=db_session,
        business_id=biz_a.id,
        as_of_date=wm_dt,
    )
    assert verdict_a.is_actionable is True
    assert verdict_a.eligibility_status == CadenceEligibilityStatus.ACTIONABLE

    # Tenant B has no watermark and low repeat buyers
    verdict_b = CadenceSafetyGate.evaluate_tenant_safety(
        session=db_session,
        business_id=biz_b.id,
        as_of_date=wm_dt,
    )
    assert verdict_b.is_actionable is False
    assert verdict_b.eligibility_status == CadenceEligibilityStatus.DIAGNOSTIC_ONLY

    # Non-existent or empty tenant returns BLOCKED
    verdict_invalid = CadenceSafetyGate.evaluate_tenant_safety(
        session=db_session,
        business_id="non-existent-biz",
    )
    assert verdict_invalid.eligibility_status == CadenceEligibilityStatus.BLOCKED


# =========================================================================
# 7. Seasonal Warnings Appear for Applicable Retail Contexts
# =========================================================================

def test_seasonal_warning_for_confirmed_seasonal_retail(db_session):
    biz = _seed_tenant(db_session, "biz-seasonal-retail", "Holiday Gifts Retail", industry="Retail")

    disclosure = CadenceSafetyGate.resolve_seasonal_context(
        session=db_session,
        business_id=biz.id,
        configured_context="seasonal",
    )

    assert disclosure.has_seasonal_caution is True
    assert disclosure.context_type == SeasonalContextType.CONFIRMED_SEASONAL
    assert "Seasonal Retail Inactivity Advisory" in disclosure.caution_title
    assert "demand cycles or holiday purchasing rather than customer churn" in disclosure.caution_message
    assert disclosure.customer_level_claim_permitted is False


# =========================================================================
# 8. Unknown Seasonal Context Does Not Create False Customer Classification
# =========================================================================

def test_unknown_seasonal_context_disclosure(db_session):
    biz = _seed_tenant(db_session, "biz-unknown-season", "Generic Goods", industry="Retail & Distribution")

    disclosure = CadenceSafetyGate.resolve_seasonal_context(
        session=db_session,
        business_id=biz.id,
        configured_context=None,
    )

    assert disclosure.has_seasonal_caution is True
    assert disclosure.context_type == SeasonalContextType.UNKNOWN_SEASONAL_CONTEXT
    assert "Retail Seasonality Advisory" in disclosure.caution_title
    assert "cannot distinguish seasonal pauses from customer attrition" in disclosure.caution_message
    assert disclosure.customer_level_claim_permitted is False


# =========================================================================
# 9. Risk Displays and Action Paths Respect Human-Review-Only Rule
# =========================================================================

def test_automated_action_caller_blocked_unconditionally(db_session):
    res = CadenceActionGate.evaluate_action_eligibility(
        session=db_session,
        business_id="biz-test",
        action_type="send_retention_discount",
        decision_id=1,
        reviewer_id="automated_bot",
        is_automated_caller=True,
    )

    assert res.is_allowed is False
    assert res.status == ActionExecutionStatus.BLOCKED_AUTOMATION_PROHIBITED
    assert "Automated customer interventions" in res.reason


def test_missing_decision_record_blocks_action(db_session):
    res = CadenceActionGate.evaluate_action_eligibility(
        session=db_session,
        business_id="biz-test",
        action_type="send_outreach_email",
        decision_id=None,
        reviewer_id="human_analyst",
        is_automated_caller=False,
    )

    assert res.is_allowed is False
    assert res.status == ActionExecutionStatus.BLOCKED_UNAPPROVED


def test_unapproved_decision_record_blocks_action(db_session):
    biz = _seed_tenant(db_session, "biz-act-test", "Action Test Biz")
    dec = DecisionRecord(
        id=901,
        business_id=biz.id,
        organization_id="org-biz-act-test",
        recommendation_text="Send 15% discount to dormant repeat buyers",
        status="PENDING",
    )
    db_session.add(dec)
    db_session.commit()

    res = CadenceActionGate.evaluate_action_eligibility(
        session=db_session,
        business_id=biz.id,
        action_type="send_retention_discount",
        decision_id=dec.id,
        reviewer_id="human_analyst@nexus.com",
    )

    assert res.is_allowed is False
    assert res.status == ActionExecutionStatus.BLOCKED_UNAPPROVED
    assert "Only APPROVED decisions may proceed" in res.reason


def test_approved_human_decision_allows_action(db_session):
    biz = _seed_tenant(db_session, "biz-approved-test", "Approved Action Test Biz")
    dec = DecisionRecord(
        id=902,
        business_id=biz.id,
        organization_id="org-biz-approved-test",
        recommendation_text="Manual outreach to high-value dormant customer",
        status="APPROVED",
        reviewed_by="sarah_manager@nexus.com",
        reviewed_at=datetime.now(UTC),
    )
    db_session.add(dec)
    db_session.commit()

    res = CadenceActionGate.evaluate_action_eligibility(
        session=db_session,
        business_id=biz.id,
        action_type="manual_outreach",
        decision_id=dec.id,
        reviewer_id="sarah_manager@nexus.com",
    )

    assert res.is_allowed is True
    assert res.status == ActionExecutionStatus.APPROVED_FOR_EXECUTION
    assert res.actor_is_human is True


# =========================================================================
# 10. AnalyticsService Integration and Evidence Record Generation
# =========================================================================

def test_analytics_service_cadence_analysis_integration(db_session):
    biz = _seed_tenant(db_session, "biz-svc-cadence", "Service Cadence Retail")
    _seed_customers_and_sales(db_session, biz.id, repeat_buyers_count=35)

    recent_now = datetime.now(UTC)
    wm_dt = recent_now - timedelta(days=5)

    WatermarkService.record_watermark(
        db_session,
        WatermarkContract(
            business_id=biz.id,
            source_id="default",
            complete_through_dt=wm_dt,
            verification_status="verified",
        ),
    )
    db_session.commit()

    service = AnalyticsService(db_session, business_id=biz.id)
    summary, verdict, evidence = service.get_customer_cadence_analysis(
        as_of_date=wm_dt,
    )

    assert summary.total_customers_evaluated > 0
    assert verdict.is_actionable is True
    assert verdict.eligibility_status == CadenceEligibilityStatus.ACTIONABLE
    assert evidence.metric == "customer_cadence_analysis"
    assert "customers" in evidence.source_tables
    assert "tenant_ingestion_watermarks" in evidence.source_tables
    assert evidence.result_summary["is_actionable"] is True
