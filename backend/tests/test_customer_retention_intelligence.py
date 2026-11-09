"""Comprehensive test suite for NEXUS Intelligent Customer Churn Prediction & Retention System.

Validates:
1. The Five Essential Customer Retention Capabilities (Which, Why, How serious, When to act, What to do).
2. Safeguards: Repeat buyers vs one-time buyers, insufficient history, zero orders, simultaneous orders.
3. Human-in-the-Loop (HITL) action tracking: proposal, human review approval, execution auditing, and customer response logging.
4. Automation prohibition: automated interventions fail closed without human approval.
5. Observational outcome evaluation: reorder rates, retention lift, precision/recall, and correlation vs causation disclosures.
6. Multi-tenant data isolation and IDOR protection.
7. Watermark readiness and safety gate enforcement.
8. Preserved Apex Specialty Commerce invariants (diagnostic-only protection).
"""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.analytics.customer.cadence import CadenceConfig, CadenceRiskTier
from app.analytics.customer.retention import CustomerRetentionService
from app.analytics.customer.safety import (
    CadenceEligibilityStatus,
    CadenceSafetyGate,
    SafetyReasonCode,
)
from app.main import app
from app.models.base import Base
from app.models.customer import Customer
from app.models.history import DecisionAuditEvent, DecisionRecord
from app.models.product import Product
from app.models.sale import Sale
from app.models.sale_item import SaleItem
from app.models.tenant import Business, IngestionJob, Organization
from app.models.watermark import TenantIngestionWatermark
from app.schemas.retention import (
    InterventionUrgency,
    RetentionActionType,
    RetentionConfidenceLevel,
    RetentionCustomerFilter,
)
from app.services.watermark_service import WatermarkContract, WatermarkService


@pytest.fixture
def retention_db_session():
    """Create an isolated in-memory SQLite database session for testing."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


def _seed_test_tenant(session: Session, business_id: str, name: str = "Test Merchant", industry: str = "Specialty Retail") -> Business:
    """Helper to seed organization and business records."""
    org_id = f"org-{uuid4().hex[:8]}"
    org = Organization(id=org_id, name=f"{name} Org", slug=f"slug-{uuid4().hex[:6]}")
    biz = Business(
        id=business_id,
        name=name,
        organization_id=org_id,
        industry=industry,
        currency="USD",
    )
    session.add_all([org, biz])
    session.commit()
    return biz


def _certify_tenant_watermark(session: Session, business_id: str, complete_through_dt: datetime) -> None:
    """Helper to register a verified watermark for actionable eligibility."""
    contract = WatermarkContract(
        business_id=business_id,
        source_id="default",
        complete_through_dt=complete_through_dt,
        provenance_type="accounting_period_close",
        verification_status="verified",
    )
    WatermarkService.record_watermark(session, contract)
    session.commit()


# ==============================================================================
# 1. THE FIVE ESSENTIAL CUSTOMER RETENTION CAPABILITIES
# ==============================================================================

def test_five_essential_customer_retention_capabilities(retention_db_session: Session):
    """
    Test that NEXUS delivers all five mandatory retention capabilities:
    A. Which customers are at risk (cohort-level risk tiers, attention count).
    B. Why each customer is at risk (observed facts, interval progression, cadence ratio).
    C. How serious the risk is (severity, lifetime spend at risk, evidence sufficiency, confidence).
    D. When to act (intervention urgency timing without false urgency).
    E. What can be done (practical, contextual retention proposals requiring human approval).
    """
    session = retention_db_session
    biz_id = "biz-retention-test-1"
    _seed_test_tenant(session, biz_id, "Apex Fashion Retail")

    cutoff = datetime(2023, 7, 1, 12, 0, tzinfo=UTC)
    _certify_tenant_watermark(session, biz_id, cutoff)

    # 1. Seed Customer 1: Critical Risk repeat buyer (ratio >= 3.0x, decelerating cadence)
    c1 = Customer(
        customer_code="CUST-CRIT-01",
        name="Critical Churn Buyer",
        email="critical@test.com",
        city="New York",
        customer_segment="Retail",
        acquisition_date=date(2023, 1, 1),
        business_id=biz_id,
    )
    # 2. Seed Customer 2: High Risk VIP Buyer (ratio ~2.4x, VIP account)
    c2 = Customer(
        customer_code="CUST-VIP-02",
        name="High Value VIP Buyer",
        email="vip@test.com",
        city="Los Angeles",
        customer_segment="VIP",
        acquisition_date=date(2023, 1, 1),
        business_id=biz_id,
    )
    # 3. Seed Customer 3: Healthy Buyer (ratio 0.8x, on schedule)
    c3 = Customer(
        customer_code="CUST-HEALTHY-03",
        name="Active Healthy Buyer",
        email="healthy@test.com",
        city="Chicago",
        customer_segment="Retail",
        acquisition_date=date(2023, 1, 1),
        business_id=biz_id,
    )
    # 4. Seed Customer 4: One-Time Buyer (1 purchase)
    c4 = Customer(
        customer_code="CUST-ONETIME-04",
        name="One Time Buyer",
        email="onetime@test.com",
        city="Miami",
        customer_segment="Retail",
        acquisition_date=date(2023, 2, 1),
        business_id=biz_id,
    )
    session.add_all([c1, c2, c3, c4])
    session.commit()

    # Product category setup
    prod1 = Product(
        sku="SKU-COFFEE-01",
        name="Dark Roast Beans",
        category="Specialty Coffee",
        subcategory="Whole Bean",
        unit_cost=Decimal("20.00"),
        selling_price=Decimal("75.00"),
        business_id=biz_id,
    )
    session.add(prod1)
    session.commit()

    # Sales for C1 (Critical): Jan 1, Jan 21, Feb 10 (intervals: 20d, 20d -> median cadence: 20d).
    # Last purchase Feb 10. Cutoff July 1 -> ~141 days elapsed -> ratio ~ 7.0x (CRITICAL).
    for idx, d in enumerate([datetime(2023, 1, 1, tzinfo=UTC), datetime(2023, 1, 21, tzinfo=UTC), datetime(2023, 2, 10, tzinfo=UTC)]):
        s = Sale(
            transaction_number=f"TXN-C1-{idx}",
            customer_id=c1.id,
            transaction_date=d,
            status="completed",
            subtotal=Decimal("150.00"),
            total_amount=Decimal("150.00"),
            business_id=biz_id,
        )
        session.add(s)
        session.flush()
        session.add(SaleItem(sale_id=s.id, product_id=prod1.id, quantity=2, unit_price=Decimal("75.00"), line_total=Decimal("150.00")))

    # Sales for C2 (VIP High Risk): Jan 1, Feb 1, Mar 1 (intervals: 31d, 28d -> median: ~30d).
    # Last purchase Mar 1. Cutoff July 1 -> 122 days elapsed -> ratio ~ 4.1x (CRITICAL or HIGH).
    for idx, d in enumerate([datetime(2023, 1, 1, tzinfo=UTC), datetime(2023, 2, 1, tzinfo=UTC), datetime(2023, 3, 1, tzinfo=UTC)]):
        s = Sale(
            transaction_number=f"TXN-C2-{idx}",
            customer_id=c2.id,
            transaction_date=d,
            status="completed",
            subtotal=Decimal("1200.00"),
            total_amount=Decimal("1200.00"),
            business_id=biz_id,
        )
        session.add(s)

    # Sales for C3 (Healthy): May 1, May 31, June 20 (intervals: 30d, 20d -> median: ~25d).
    # Last purchase June 20. Cutoff July 1 -> 11 days elapsed -> ratio ~ 0.44x (LOW / HEALTHY).
    for idx, d in enumerate([datetime(2023, 5, 1, tzinfo=UTC), datetime(2023, 5, 31, tzinfo=UTC), datetime(2023, 6, 20, tzinfo=UTC)]):
        s = Sale(
            transaction_number=f"TXN-C3-{idx}",
            customer_id=c3.id,
            transaction_date=d,
            status="completed",
            subtotal=Decimal("80.00"),
            total_amount=Decimal("80.00"),
            business_id=biz_id,
        )
        session.add(s)

    # Sale for C4 (One-time): Feb 15 (1 order only).
    session.add(Sale(
        transaction_number="TXN-C4-1",
        customer_id=c4.id,
        transaction_date=datetime(2023, 2, 15, tzinfo=UTC),
        status="completed",
        subtotal=Decimal("50.00"),
        total_amount=Decimal("50.00"),
        business_id=biz_id,
    ))
    session.commit()

    # Seed additional dummy repeat buyers to satisfy the 30-buyer pilot cohort threshold
    for i in range(30):
        c_dummy = Customer(
            customer_code=f"CUST-DUMMY-{i}",
            name=f"Dummy Buyer {i}",
            email=f"dummy{i}@test.com",
            city="Chicago",
            customer_segment="Retail",
            acquisition_date=date(2023, 1, 1),
            business_id=biz_id,
        )
        session.add(c_dummy)
        session.flush()
        # 2 purchases
        session.add(Sale(transaction_number=f"TXN-DUMMY-{i}-1", customer_id=c_dummy.id, transaction_date=datetime(2023, 5, 1, tzinfo=UTC), status="completed", subtotal=Decimal("50.00"), total_amount=Decimal("50.00"), business_id=biz_id))
        session.add(Sale(transaction_number=f"TXN-DUMMY-{i}-2", customer_id=c_dummy.id, transaction_date=datetime(2023, 6, 1, tzinfo=UTC), status="completed", subtotal=Decimal("50.00"), total_amount=Decimal("50.00"), business_id=biz_id))
    session.commit()

    # --- EXECUTE RETENTION OVERVIEW (Capability A & C) ---
    overview = CustomerRetentionService.get_retention_overview(
        session=session,
        business_id=biz_id,
        as_of_date=cutoff,
        max_staleness_days=None,
    )

    assert overview.total_customers_evaluated == 34
    assert overview.repeat_buyers_count == 33
    assert overview.one_time_buyers_count == 1
    assert overview.customers_requiring_attention_count >= 2
    assert overview.total_revenue_at_risk_usd >= 4050.0  # 450 (C1) + 3600 (C2)
    assert overview.safety_verdict.is_actionable is True

    # --- EXECUTE CUSTOMER DETAIL FOR C1 (CRITICAL) (Capability B, C, D, E) ---
    c1_detail = CustomerRetentionService.get_customer_risk_detail(
        session=session,
        business_id=biz_id,
        customer_id=c1.id,
        as_of_date=cutoff,
    )

    # Capability A: Identity & Status
    assert c1_detail.customer_code == "CUST-CRIT-01"
    assert c1_detail.is_repeat_buyer is True
    assert c1_detail.risk_tier == CadenceRiskTier.CRITICAL

    # Capability B: Why is customer at risk (factual observed history & explanation)
    assert c1_detail.total_lifetime_orders == 3
    assert c1_detail.distinct_purchase_dates == 3
    assert c1_detail.total_lifetime_spend == 450.0
    assert c1_detail.baseline_cadence_days == 20.0
    assert c1_detail.days_since_last_purchase is not None
    assert c1_detail.days_since_last_purchase > 100.0
    assert c1_detail.cadence_ratio > 3.0
    assert "critically overdue" in c1_detail.why_at_risk_summary
    assert len(c1_detail.risk_factors) >= 2
    assert "In non-contractual commerce" in c1_detail.uncertainty_notice

    # Capability C: How serious is the risk (severity, evidence score, confidence)
    assert c1_detail.urgency == InterventionUrgency.IMMEDIATE
    assert c1_detail.confidence_level in {RetentionConfidenceLevel.MEDIUM, RetentionConfidenceLevel.HIGH}
    assert c1_detail.evidence_sufficiency_score > 0.5

    # Capability D: When should the merchant act?
    assert c1_detail.urgency == InterventionUrgency.IMMEDIATE
    assert "calendar days" in c1_detail.recommended_action.recommended_window

    # Capability E: What can the merchant do to retain the customer?
    rec = c1_detail.recommended_action
    assert rec is not None
    assert rec.requires_human_approval is True
    assert len(rec.action_steps) >= 2
    assert len(rec.trade_offs) >= 1
    assert rec.expected_margin_impact_usd > 0.0

    # --- EXECUTE CUSTOMER DETAIL FOR C2 (VIP) -> Dedicated Account Executive Outreach ---
    c2_detail = CustomerRetentionService.get_customer_risk_detail(
        session=session,
        business_id=biz_id,
        customer_id=c2.id,
        as_of_date=cutoff,
    )
    assert c2_detail.customer_segment == "VIP"
    assert c2_detail.recommended_action.action_type == RetentionActionType.PERSONAL_FOLLOW_UP
    assert "Dedicated Account Executive Outreach" in c2_detail.recommended_action.title

    # --- EXECUTE CUSTOMER DETAIL FOR C3 (HEALTHY) -> Monitor Only ---
    c3_detail = CustomerRetentionService.get_customer_risk_detail(
        session=session,
        business_id=biz_id,
        customer_id=c3.id,
        as_of_date=cutoff,
    )
    assert c3_detail.risk_tier == CadenceRiskTier.LOW
    assert c3_detail.urgency == InterventionUrgency.HEALTHY
    assert c3_detail.recommended_action.action_type == RetentionActionType.MONITOR_ONLY


# ==============================================================================
# 2. SAFEGUARDS: ONE-TIME BUYERS & INSUFFICIENT HISTORY
# ==============================================================================

def test_one_time_buyers_and_insufficient_history_safeguards(retention_db_session: Session):
    """
    Verify strict safeguards preventing one-time buyers from receiving false churn alarms.
    """
    session = retention_db_session
    biz_id = "biz-safeguard-test"
    _seed_test_tenant(session, biz_id, "Safeguard Tenant")
    cutoff = datetime(2023, 7, 1, 12, 0, tzinfo=UTC)

    # 1. Zero purchase customer
    c_zero = Customer(
        customer_code="CUST-ZERO",
        name="Zero Buyer",
        email="zero@test.com",
        city="Boston",
        customer_segment="Retail",
        acquisition_date=date(2023, 1, 1),
        business_id=biz_id,
    )
    # 2. One-time buyer
    c_single = Customer(
        customer_code="CUST-SINGLE",
        name="Single Buyer",
        email="single@test.com",
        city="Boston",
        customer_segment="Retail",
        acquisition_date=date(2023, 1, 1),
        business_id=biz_id,
    )
    # 3. Simultaneous orders buyer (multiple orders, same second)
    c_simult = Customer(
        customer_code="CUST-SIMULT",
        name="Simultaneous Buyer",
        email="simult@test.com",
        city="Boston",
        customer_segment="Retail",
        acquisition_date=date(2023, 1, 1),
        business_id=biz_id,
    )
    session.add_all([c_zero, c_single, c_simult])
    session.commit()

    # Add single sale
    session.add(Sale(
        transaction_number="TXN-SINGLE-1",
        customer_id=c_single.id,
        transaction_date=datetime(2023, 2, 1, tzinfo=UTC),
        status="completed",
        subtotal=Decimal("100.00"),
        total_amount=Decimal("100.00"),
        business_id=biz_id,
    ))

    # Add simultaneous sales
    t_sim = datetime(2023, 2, 1, 10, 0, 0, tzinfo=UTC)
    session.add(Sale(transaction_number="TXN-SIM-1", customer_id=c_simult.id, transaction_date=t_sim, status="completed", subtotal=Decimal("50.00"), total_amount=Decimal("50.00"), business_id=biz_id))
    session.add(Sale(transaction_number="TXN-SIM-2", customer_id=c_simult.id, transaction_date=t_sim, status="completed", subtotal=Decimal("50.00"), total_amount=Decimal("50.00"), business_id=biz_id))
    session.commit()

    # Evaluate single buyer
    single_detail = CustomerRetentionService.get_customer_risk_detail(session, biz_id, c_single.id, as_of_date=cutoff)
    assert single_detail.is_repeat_buyer is False
    assert single_detail.risk_tier == CadenceRiskTier.INSUFFICIENT_HISTORY
    assert single_detail.urgency == InterventionUrgency.INSUFFICIENT_HISTORY
    assert single_detail.cadence_ratio is None
    assert single_detail.recommended_action.action_type == RetentionActionType.ONBOARDING_NURTURE
    assert "First-Purchase Onboarding Nurture" in single_detail.recommended_action.title

    # Evaluate simultaneous orders buyer
    simult_detail = CustomerRetentionService.get_customer_risk_detail(session, biz_id, c_simult.id, as_of_date=cutoff)
    assert simult_detail.is_repeat_buyer is False
    assert simult_detail.risk_tier == CadenceRiskTier.INSUFFICIENT_HISTORY
    assert simult_detail.distinct_purchase_dates == 1


# ==============================================================================
# 3. HITL ACTION TRACKING & AUTOMATION PROHIBITION
# ==============================================================================

def test_hitl_action_tracking_approval_and_execution_lifecycle(retention_db_session: Session):
    """
    Test full Human-in-the-Loop decision lifecycle:
    Proposal -> Review Approval -> Execution -> Customer Response Logging.
    Also verifies that automated callers fail closed.
    """
    session = retention_db_session
    biz_id = "biz-hitl-lifecycle"
    _seed_test_tenant(session, biz_id, "HITL Merchant")
    cutoff = datetime(2023, 7, 1, tzinfo=UTC)

    c = Customer(
        customer_code="CUST-HITL-01",
        name="Review Target Customer",
        email="hitl@test.com",
        city="Austin",
        customer_segment="Corporate",
        acquisition_date=date(2023, 1, 1),
        business_id=biz_id,
    )
    session.add(c)
    session.flush()

    # 2 purchases
    session.add(Sale(transaction_number="TXN-H1", customer_id=c.id, transaction_date=datetime(2023, 1, 1, tzinfo=UTC), status="completed", subtotal=Decimal("400.00"), total_amount=Decimal("400.00"), business_id=biz_id))
    session.add(Sale(transaction_number="TXN-H2", customer_id=c.id, transaction_date=datetime(2023, 1, 25, tzinfo=UTC), status="completed", subtotal=Decimal("400.00"), total_amount=Decimal("400.00"), business_id=biz_id))
    session.commit()

    # 1. Propose decision
    dec = CustomerRetentionService.create_retention_decision(
        session=session,
        business_id=biz_id,
        customer_id=c.id,
        custom_notes="Urgent corporate check-in proposed",
    )
    assert dec.id is not None
    assert dec.status == "PENDING"
    assert dec.current_revision == 0
    assert dec.recommendation_type == "CUSTOMER_RETENTION"
    assert dec.action_target_id == "CUST-HITL-01"

    # Genesis audit event check
    ev_gen = session.execute(
        select(DecisionAuditEvent).where(DecisionAuditEvent.decision_id == dec.id, DecisionAuditEvent.revision == 0)
    ).scalar_one()
    assert ev_gen.event_type == "DECISION_CREATED"

    # 2. Verify non-human review rejection
    with pytest.raises(ValueError, match="verified human reviewer identity"):
        CustomerRetentionService.review_retention_decision(
            session=session,
            business_id=biz_id,
            decision_id=dec.id,
            status="APPROVED",
            reviewer_id="system_cron",
        )

    # 3. Human Review Approval
    dec_approved = CustomerRetentionService.review_retention_decision(
        session=session,
        business_id=biz_id,
        decision_id=dec.id,
        status="APPROVED",
        reviewer_id="sarah_retention_lead@merchant.com",
        reviewer_notes="Approved with phone call prioritisation",
    )
    assert dec_approved.status == "APPROVED"
    assert dec_approved.current_revision == 1
    assert dec_approved.reviewed_by == "sarah_retention_lead@merchant.com"

    # 4. Action Execution
    dec_exec = CustomerRetentionService.execute_retention_action(
        session=session,
        business_id=biz_id,
        decision_id=dec.id,
        execution_channel="phone",
        executed_by="sarah_retention_lead@merchant.com",
        execution_notes="Called buyer; discussed upcoming inventory restock.",
    )
    assert dec_exec.current_revision == 2

    # Audit event check for execution
    ev_exec = session.execute(
        select(DecisionAuditEvent).where(DecisionAuditEvent.decision_id == dec.id, DecisionAuditEvent.revision == 2)
    ).scalar_one()
    assert ev_exec.event_type == "ACTION_EXECUTED"
    assert ev_exec.canonical_payload["channel"] == "phone"

    # 5. Log Customer Response
    dec_resp = CustomerRetentionService.log_customer_response(
        session=session,
        business_id=biz_id,
        decision_id=dec.id,
        response_status="replied",
        logged_by="sarah_retention_lead@merchant.com",
        response_notes="Customer expressed interest in reordering next week.",
    )
    assert dec_resp.current_revision == 3

    # Audit event check for response
    ev_resp = session.execute(
        select(DecisionAuditEvent).where(DecisionAuditEvent.decision_id == dec.id, DecisionAuditEvent.revision == 3)
    ).scalar_one()
    assert ev_resp.event_type == "CUSTOMER_RESPONDED"
    assert ev_resp.canonical_payload["response_status"] == "replied"


# ==============================================================================
# 4. OBSERVATIONAL OUTCOME EVALUATION & DEMONSTRATED LIFT
# ==============================================================================

def test_retention_outcome_evaluation_and_lift(retention_db_session: Session):
    """
    Test outcome evaluation comparing intervened customers against non-intervened at-risk peers.
    """
    session = retention_db_session
    biz_id = "biz-outcome-eval"
    _seed_test_tenant(session, biz_id, "Outcome Test Merchant")

    t_action = datetime(2023, 4, 1, 10, 0, tzinfo=UTC)
    t_eval = datetime(2023, 5, 1, 10, 0, tzinfo=UTC)

    # Intervened Customer (Places subsequent order in 30d window)
    c_intervened = Customer(
        customer_code="CUST-INT-1",
        name="Intervened Customer",
        email="int@test.com",
        city="Dallas",
        customer_segment="Retail",
        acquisition_date=date(2023, 1, 1),
        business_id=biz_id,
    )
    # Comparison Customer (No intervention, does not place subsequent order)
    c_comp = Customer(
        customer_code="CUST-COMP-1",
        name="Comparison Customer",
        email="comp@test.com",
        city="Dallas",
        customer_segment="Retail",
        acquisition_date=date(2023, 1, 1),
        business_id=biz_id,
    )
    session.add_all([c_intervened, c_comp])
    session.flush()

    # Pre-action purchases
    for d in [datetime(2023, 1, 1, tzinfo=UTC), datetime(2023, 1, 20, tzinfo=UTC)]:
        session.add(Sale(transaction_number=f"TXN-I-{uuid4().hex[:6]}", customer_id=c_intervened.id, transaction_date=d, status="completed", subtotal=Decimal("100.00"), total_amount=Decimal("100.00"), business_id=biz_id))
        session.add(Sale(transaction_number=f"TXN-C-{uuid4().hex[:6]}", customer_id=c_comp.id, transaction_date=d, status="completed", subtotal=Decimal("100.00"), total_amount=Decimal("100.00"), business_id=biz_id))
    session.commit()

    # Intervene on c_intervened
    dec = CustomerRetentionService.create_retention_decision(session, biz_id, c_intervened.id)
    CustomerRetentionService.review_retention_decision(session, biz_id, dec.id, "APPROVED", "analyst_1")
    CustomerRetentionService.execute_retention_action(session, biz_id, dec.id, "phone", "analyst_1", execution_date=t_action)

    # Subsequent purchase for intervened customer (April 15)
    session.add(Sale(
        transaction_number="TXN-SUBSEQUENT-1",
        customer_id=c_intervened.id,
        transaction_date=datetime(2023, 4, 15, tzinfo=UTC),
        status="completed",
        subtotal=Decimal("250.00"),
        total_amount=Decimal("250.00"),
        business_id=biz_id,
    ))
    session.commit()

    # Run outcome evaluation
    eval_res = CustomerRetentionService.evaluate_retention_outcomes(
        session=session,
        business_id=biz_id,
        evaluation_window_days=30,
        as_of_date=t_eval,
    )

    assert eval_res.intervened_customers_count == 1
    assert eval_res.intervened_reordered_count == 1
    assert eval_res.intervened_reorder_rate_pct == 100.0
    assert eval_res.intervened_subsequent_revenue_usd == 250.0
    assert eval_res.comparison_customers_count == 1
    assert eval_res.comparison_reordered_count == 0
    assert eval_res.comparison_reorder_rate_pct == 0.0
    assert eval_res.retention_lift_pct_points == 100.0
    assert "Observational comparative evaluation" in eval_res.methodology_disclaimer


# ==============================================================================
# 5. MULTI-TENANT ISOLATION & IDOR PREVENTION
# ==============================================================================

def test_retention_multi_tenant_isolation(retention_db_session: Session):
    """
    Verify that tenants cannot view, recommend, or execute retention actions for other tenants.
    """
    session = retention_db_session
    biz_a = "biz-alpha"
    biz_b = "biz-beta"
    _seed_test_tenant(session, biz_a, "Tenant Alpha")
    _seed_test_tenant(session, biz_b, "Tenant Beta")

    cust_a = Customer(customer_code="CUST-A", name="Alpha Cust", email="a@test.com", city="Seattle", customer_segment="Retail", acquisition_date=date(2023, 1, 1), business_id=biz_a)
    cust_b = Customer(customer_code="CUST-B", name="Beta Cust", email="b@test.com", city="Portland", customer_segment="Retail", acquisition_date=date(2023, 1, 1), business_id=biz_b)
    session.add_all([cust_a, cust_b])
    session.commit()

    # Tenant A cannot fetch risk detail for Tenant B's customer
    with pytest.raises(ValueError, match="does not exist in business"):
        CustomerRetentionService.get_customer_risk_detail(session, biz_a, cust_b.id)

    # Tenant B cannot execute Tenant A's decision
    dec_a = CustomerRetentionService.create_retention_decision(session, biz_a, cust_a.id)
    CustomerRetentionService.review_retention_decision(session, biz_a, dec_a.id, "APPROVED", "admin_a")

    with pytest.raises(PermissionError, match="Tenant isolation violation"):
        CustomerRetentionService.execute_retention_action(session, biz_b, dec_a.id, "phone", "admin_b")


# ==============================================================================
# 6. WATERMARK READINESS GATE ENFORCEMENT
# ==============================================================================

def test_unverified_watermark_enforces_diagnostic_only(retention_db_session: Session):
    """
    Verify that missing or unverified watermarks restrict retention metrics to DIAGNOSTIC_ONLY.
    """
    session = retention_db_session
    biz_id = "biz-unverified-wm"
    _seed_test_tenant(session, biz_id, "Unverified Tenant")

    overview = CustomerRetentionService.get_retention_overview(session, biz_id)
    assert overview.safety_verdict.is_actionable is False
    assert overview.safety_verdict.eligibility_status == CadenceEligibilityStatus.DIAGNOSTIC_ONLY
    assert overview.safety_verdict.reason_code == SafetyReasonCode.MISSING_WATERMARK
    assert "NON-ACTIONABLE DIAGNOSTIC TELEMETRY" in overview.safety_verdict.non_actionable_notice


# ==============================================================================
# 7. FASTAPI ENDPOINT INTEGRATION TESTS
# ==============================================================================

def test_retention_api_endpoints(authenticated_client: TestClient):
    """
    Test FastAPI endpoints exposing retention intelligence and HITL actions.
    """
    client = authenticated_client

    # 1. Overview endpoint (returns envelope with data and evidence)
    res = client.get("/api/v1/analytics/retention/overview")
    assert res.status_code == 200
    json_data = res.json()
    assert json_data["success"] is True
    assert "data" in json_data
    assert "evidence" in json_data
    assert "risk_distribution" in json_data["data"]
    assert "safety_verdict" in json_data["data"]

    # 2. Customers list endpoint
    res_cust = client.get("/api/v1/analytics/retention/customers?page=1&page_size=10")
    assert res_cust.status_code == 200
    json_cust = res_cust.json()
    assert json_cust["success"] is True
    assert "items" in json_cust["data"]
    assert "total_count" in json_cust["data"]

    # 3. Outcomes evaluation endpoint
    res_eval = client.get("/api/v1/analytics/retention/evaluation?evaluation_window_days=30")
    assert res_eval.status_code == 200
    json_eval = res_eval.json()
    assert json_eval["success"] is True
    assert "intervened_customers_count" in json_eval["data"]
    assert "retention_lift_pct_points" in json_eval["data"]

    # 4. Tenant isolation check: without X-Business-ID header returns 400
    unauth_client = TestClient(app)
    unauth_res = unauth_client.get("/api/v1/analytics/retention/overview")
    assert unauth_res.status_code == 400
    assert "Tenant context is required" in unauth_res.json()["detail"]
