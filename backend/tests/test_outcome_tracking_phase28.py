"""Tests for NEXUS Phase 28 Stage 2: Outcome Tracking and Maturity.

Verifies:
1. Valid and invalid outcome observation recording (metric, units, bounds, dates, finite values).
2. Multi-tenant isolation and cross-tenant IDOR protection.
3. Idempotent replays and conflicting duplicate detection.
4. Window maturity states: NOT_YET_DUE, DUE_INSUFFICIENT, MATURE_SUFFICIENT, CONFLICTING_OR_INVALID.
5. Incomplete, missing, duplicate, and partial observation coverage calculation.
6. Deferred decision lifecycle: evaluation window inactive until explicit action execution or monitoring start.
7. Rejected decision lifecycle: tracks observed status quo, not counterfactual performance.
8. Deterministic evidence quality grading (HIGH / MEDIUM / LOW) and clear explanations.
9. Strict causal boundaries: no causal attribution claimed without causal design.
10. REST API endpoints for outcome recording, listing, action execution, and evaluation.
"""

from datetime import UTC, datetime, timedelta

import pytest
from app.analytics.outcome.schemas import (
    BaselineMetricsSnapshot,
    DecisionCreatePayload,
    DecisionReviewPayload,
    EvidenceQualityGrade,
    OutcomeActionExecutionRequest,
    OutcomeMaturityStatus,
    OutcomeObservationCreateRequest,
    RecommendationSnapshot,
)
from app.analytics.outcome.service import (
    ConflictingObservationError,
    DecisionMemoryService,
    IdempotencyConflictError,
)
from app.models.history import DecisionOutcomeObservation, DecisionRecord
from app.models.tenant import Business, Organization, OrganizationMembership, UserIdentity
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

# ---------------------------------------------------------------------------
# FIXTURES
# ---------------------------------------------------------------------------

@pytest.fixture
def tenant_fixture(db_session: Session):
    """Seed Org A, User A, and Business A."""
    org_a = Organization(id="org_alpha_p28_s2", name="Alpha Org", slug="alpha-org-p28-s2")
    db_session.add(org_a)
    db_session.flush()

    user_a = UserIdentity(
        id="usr_alpha_p28_s2",
        email="analyst_a_s2@alpha.internal",
        full_name="Alpha Analyst S2",
        password_hash="pw_hash_test",
        is_active=True,
        is_verified=True,
    )
    db_session.add(user_a)
    db_session.flush()

    mem_a = OrganizationMembership(
        user_id=user_a.id,
        organization_id=org_a.id,
        role="owner",
    )
    db_session.add(mem_a)

    biz_a = Business(
        id="biz_alpha_p28_s2",
        organization_id=org_a.id,
        name="Alpha Retail S2",
        status="active",
    )
    db_session.add(biz_a)
    db_session.commit()

    return {"org": org_a, "user": user_a, "biz": biz_a}


@pytest.fixture
def foreign_tenant_fixture(db_session: Session):
    """Seed Org B, User B, and Business B for cross-tenant isolation testing."""
    org_b = Organization(id="org_bravo_p28_s2", name="Bravo Org", slug="bravo-org-p28-s2")
    db_session.add(org_b)
    db_session.flush()

    user_b = UserIdentity(
        id="usr_bravo_p28_s2",
        email="analyst_b_s2@bravo.internal",
        full_name="Bravo Analyst S2",
        password_hash="pw_hash_test",
        is_active=True,
        is_verified=True,
    )
    db_session.add(user_b)
    db_session.flush()

    mem_b = OrganizationMembership(
        user_id=user_b.id,
        organization_id=org_b.id,
        role="member",
    )
    db_session.add(mem_b)

    biz_b = Business(
        id="biz_bravo_p28_s2",
        organization_id=org_b.id,
        name="Bravo Retail S2",
        status="active",
    )
    db_session.add(biz_b)
    db_session.commit()

    return {"org": org_b, "user": user_b, "biz": biz_b}


def _create_test_decision(
    db: Session,
    user: UserIdentity,
    biz_id: str,
    status: str = "APPROVED",
    window_days: int = 30,
    reviewed_at: datetime | None = None,
) -> DecisionRecord:
    """Helper to create a standard decision record with baseline metrics."""
    base_snap = BaselineMetricsSnapshot(
        window_start="2026-08-01T00:00:00Z",
        window_end="2026-08-31T00:00:00Z",
        window_days=31,
        metrics={"revenue": 10000.0, "stockout_days": 2.0},
        metric_definitions={"revenue": "Sum of completed orders"},
        provenance={"dataset": "pos_v1"},
    )
    rec_snap = RecommendationSnapshot(
        recommendation_type="INVENTORY_REORDER",
        action_target_type="SKU",
        action_target_id="SKU-PREM-101",
        point_recommendation={"recommended_reorder_qty": 500},
        observed_facts={"current_stock": 50},
    )
    record = DecisionMemoryService.create_decision_record(
        db=db,
        current_user=user,
        business_id=biz_id,
        payload=DecisionCreatePayload(
            recommendation_text="Reorder 500 units of SKU-PREM-101",
            recommendation_snapshot=rec_snap,
            baseline_metrics_snapshot=base_snap,
            outcome_window_days=window_days,
        ),
        idempotency_key=f"idemp_dec_{datetime.now(UTC).timestamp()}_{status}",
    )
    if status != "PENDING":
        DecisionMemoryService.record_human_review(
            db=db,
            current_user=user,
            business_id=biz_id,
            decision_id=record.id,
            review_payload=DecisionReviewPayload(status=status),
            idempotency_key=f"idemp_rev_{record.id}_{status}",
        )
        if reviewed_at:
            record.reviewed_at = reviewed_at
            db.commit()
            db.refresh(record)
    return record


# ---------------------------------------------------------------------------
# 1. OUTCOME OBSERVATION RECORDING & AUDIT LINKAGE
# ---------------------------------------------------------------------------

def test_record_outcome_observation_valid_and_audit_linkage(db_session: Session, tenant_fixture):
    """Test recording a valid outcome observation links to decision and updates hash chain."""
    user = tenant_fixture["user"]
    biz = tenant_fixture["biz"]

    decision = _create_test_decision(db_session, user, biz.id, status="APPROVED")

    p_start = datetime(2026, 9, 1, 0, 0, 0, tzinfo=UTC)
    p_end = datetime(2026, 9, 15, 0, 0, 0, tzinfo=UTC)

    obs = DecisionMemoryService.record_outcome_observation(
        db=db_session,
        current_user=user,
        business_id=biz.id,
        decision_id=decision.id,
        payload=OutcomeObservationCreateRequest(
            metric_name="revenue",
            unit="USD",
            period_start=p_start,
            period_end=p_end,
            observed_value=5500.0,
            source="pos_sales_stream",
            dataset_version="ds_v2_sept",
            coverage_pct=100.0,
            is_partial=False,
            idempotency_key="idemp_obs_01",
            metadata={"sensor": "pos_terminal_01"},
        ),
    )

    assert obs.id is not None
    assert obs.decision_id == decision.id
    assert obs.observed_value == 5500.0
    assert obs.metric_name == "revenue"

    # Verify audit chain integrity with new event
    report = DecisionMemoryService.verify_decision_audit_chain(
        db=db_session,
        current_user=user,
        business_id=biz.id,
        decision_id=decision.id,
    )
    assert report.is_valid is True
    assert report.total_events == 3  # Genesis (0) + Approved (1) + Outcome Observation (2)


def test_record_outcome_observation_validation_errors(db_session: Session, tenant_fixture):
    """Verify rejection of inverted dates, non-finite values, negative metrics, and unit mismatches."""
    user = tenant_fixture["user"]
    biz = tenant_fixture["biz"]
    decision = _create_test_decision(db_session, user, biz.id, status="APPROVED")

    t1 = datetime(2026, 9, 1, tzinfo=UTC)
    t2 = datetime(2026, 9, 10, tzinfo=UTC)

    # 1. Inverted dates: period_start >= period_end
    with pytest.raises(HTTPException) as exc:
        DecisionMemoryService.record_outcome_observation(
            db=db_session,
            current_user=user,
            business_id=biz.id,
            decision_id=decision.id,
            payload=OutcomeObservationCreateRequest(
                metric_name="revenue",
                unit="USD",
                period_start=t2,
                period_end=t1,  # Inverted!
                observed_value=100.0,
                source="pos",
                idempotency_key="idemp_inv_date",
            ),
        )
    assert exc.value.status_code == 400
    assert "period_start" in exc.value.detail

    # 2. Non-finite values: NaN or Inf
    with pytest.raises(HTTPException) as exc:
        DecisionMemoryService.record_outcome_observation(
            db=db_session,
            current_user=user,
            business_id=biz.id,
            decision_id=decision.id,
            payload=OutcomeObservationCreateRequest(
                metric_name="revenue",
                unit="USD",
                period_start=t1,
                period_end=t2,
                observed_value=float("nan"),
                source="pos",
                idempotency_key="idemp_nan",
            ),
        )
    assert exc.value.status_code == 400
    assert "finite number" in exc.value.detail

    # 3. Negative value on non-negative metric (revenue)
    with pytest.raises(HTTPException) as exc:
        DecisionMemoryService.record_outcome_observation(
            db=db_session,
            current_user=user,
            business_id=biz.id,
            decision_id=decision.id,
            payload=OutcomeObservationCreateRequest(
                metric_name="revenue",
                unit="USD",
                period_start=t1,
                period_end=t2,
                observed_value=-500.0,
                source="pos",
                idempotency_key="idemp_neg",
            ),
        )
    assert exc.value.status_code == 400
    assert "cannot have a negative observed value" in exc.value.detail

    # 4. Unit mismatch: record valid USD observation first, then attempt EUR for same metric
    DecisionMemoryService.record_outcome_observation(
        db=db_session,
        current_user=user,
        business_id=biz.id,
        decision_id=decision.id,
        payload=OutcomeObservationCreateRequest(
            metric_name="revenue",
            unit="USD",
            period_start=t1,
            period_end=t2,
            observed_value=1000.0,
            source="pos",
            idempotency_key="idemp_usd_ok",
        ),
    )

    t3 = datetime(2026, 9, 20, tzinfo=UTC)
    with pytest.raises(HTTPException) as exc:
        DecisionMemoryService.record_outcome_observation(
            db=db_session,
            current_user=user,
            business_id=biz.id,
            decision_id=decision.id,
            payload=OutcomeObservationCreateRequest(
                metric_name="revenue",
                unit="EUR",  # Mismatch!
                period_start=t2,
                period_end=t3,
                observed_value=900.0,
                source="pos",
                idempotency_key="idemp_eur_mismatch",
            ),
        )
    assert exc.value.status_code == 400
    assert "Unit mismatch" in exc.value.detail


# ---------------------------------------------------------------------------
# 2. MULTI-TENANT ISOLATION (IDOR DEFENSES)
# ---------------------------------------------------------------------------

def test_cross_tenant_idor_protection(db_session: Session, tenant_fixture, foreign_tenant_fixture):
    """Verify User B cannot record, list, or evaluate outcomes on Business A's decisions."""
    user_a = tenant_fixture["user"]
    biz_a = tenant_fixture["biz"]
    user_b = foreign_tenant_fixture["user"]

    decision_a = _create_test_decision(db_session, user_a, biz_a.id, status="APPROVED")

    # 1. User B attempts to record outcome on Decision A
    with pytest.raises(HTTPException) as exc:
        DecisionMemoryService.record_outcome_observation(
            db=db_session,
            current_user=user_b,
            business_id=biz_a.id,
            decision_id=decision_a.id,
            payload=OutcomeObservationCreateRequest(
                metric_name="revenue",
                unit="USD",
                period_start=datetime(2026, 9, 1, tzinfo=UTC),
                period_end=datetime(2026, 9, 10, tzinfo=UTC),
                observed_value=200.0,
                source="pos",
                idempotency_key="idemp_idor_01",
            ),
        )
    assert exc.value.status_code == 403

    # 2. User B attempts to list outcomes on Decision A
    with pytest.raises(HTTPException) as exc:
        DecisionMemoryService.list_outcome_observations(
            db=db_session,
            current_user=user_b,
            business_id=biz_a.id,
            decision_id=decision_a.id,
        )
    assert exc.value.status_code == 403

    # 3. User B attempts to evaluate outcome on Decision A
    with pytest.raises(HTTPException) as exc:
        DecisionMemoryService.evaluate_decision_outcome(
            db=db_session,
            current_user=user_b,
            business_id=biz_a.id,
            decision_id=decision_a.id,
        )
    assert exc.value.status_code == 403


# ---------------------------------------------------------------------------
# 3. IDEMPOTENCY & CONFLICTING DUPLICATE PROTECTION
# ---------------------------------------------------------------------------

def test_outcome_idempotency_replay_and_conflict_detection(db_session: Session, tenant_fixture):
    """Verify identical payload replay succeeds, while payload modifications or contradictory periods raise 409."""
    user = tenant_fixture["user"]
    biz = tenant_fixture["biz"]
    decision = _create_test_decision(db_session, user, biz.id, status="APPROVED")

    t1 = datetime(2026, 9, 1, tzinfo=UTC)
    t2 = datetime(2026, 9, 15, tzinfo=UTC)

    req = OutcomeObservationCreateRequest(
        metric_name="revenue",
        unit="USD",
        period_start=t1,
        period_end=t2,
        observed_value=3000.0,
        source="pos",
        idempotency_key="idemp_test_idemp_key",
    )

    # First execution
    obs1 = DecisionMemoryService.record_outcome_observation(
        db=db_session, current_user=user, business_id=biz.id, decision_id=decision.id, payload=req
    )

    # Identical replay returns same observation
    obs2 = DecisionMemoryService.record_outcome_observation(
        db=db_session, current_user=user, business_id=biz.id, decision_id=decision.id, payload=req
    )
    assert obs1.id == obs2.id

    # Replay same key with conflicting observed_value -> 409 IdempotencyConflictError
    conflicting_key_req = OutcomeObservationCreateRequest(
        metric_name="revenue",
        unit="USD",
        period_start=t1,
        period_end=t2,
        observed_value=9999.0,  # Conflicting value
        source="pos",
        idempotency_key="idemp_test_idemp_key",
    )
    with pytest.raises(IdempotencyConflictError):
        DecisionMemoryService.record_outcome_observation(
            db=db_session, current_user=user, business_id=biz.id, decision_id=decision.id, payload=conflicting_key_req
        )

    # Different idempotency key but same metric and identical period with conflicting value -> 409 ConflictingObservationError
    contradictory_period_req = OutcomeObservationCreateRequest(
        metric_name="revenue",
        unit="USD",
        period_start=t1,
        period_end=t2,
        observed_value=7500.0,  # Contradicts obs1's 3000.0 for [t1, t2]
        source="pos",
        idempotency_key="idemp_different_key_same_period",
    )
    with pytest.raises(ConflictingObservationError):
        DecisionMemoryService.record_outcome_observation(
            db=db_session, current_user=user, business_id=biz.id, decision_id=decision.id, payload=contradictory_period_req
        )


# ---------------------------------------------------------------------------
# 4. OUTCOME-WINDOW MATURITY EVALUATION
# ---------------------------------------------------------------------------

def test_outcome_maturity_not_yet_due(db_session: Session, tenant_fixture):
    """Verify evaluation returns NOT_YET_DUE when calendar window has not elapsed."""
    user = tenant_fixture["user"]
    biz = tenant_fixture["biz"]

    # Decision reviewed 5 days ago with 30-day window
    review_date = datetime(2026, 9, 1, 0, 0, 0, tzinfo=UTC)
    eval_date = datetime(2026, 9, 6, 0, 0, 0, tzinfo=UTC)  # Only 5 days elapsed

    decision = _create_test_decision(
        db_session, user, biz.id, status="APPROVED", window_days=30, reviewed_at=review_date
    )

    # Record 5 days of observations
    DecisionMemoryService.record_outcome_observation(
        db=db_session,
        current_user=user,
        business_id=biz.id,
        decision_id=decision.id,
        payload=OutcomeObservationCreateRequest(
            metric_name="revenue",
            unit="USD",
            period_start=review_date,
            period_end=eval_date,
            observed_value=1800.0,
            source="pos_sales_stream",
            idempotency_key="obs_5days",
        ),
    )

    report = DecisionMemoryService.evaluate_decision_outcome(
        db=db_session,
        current_user=user,
        business_id=biz.id,
        decision_id=decision.id,
        as_of=eval_date,
    )

    assert report.is_window_elapsed is False
    assert report.maturity_status == OutcomeMaturityStatus.NOT_YET_DUE
    assert report.evidence_quality == EvidenceQualityGrade.LOW
    assert "remaining" in report.evidence_explanation


def test_outcome_maturity_due_but_insufficient(db_session: Session, tenant_fixture):
    """Verify evaluation returns DUE_INSUFFICIENT when window elapsed but data is incomplete (< 90%)."""
    user = tenant_fixture["user"]
    biz = tenant_fixture["biz"]

    review_date = datetime(2026, 9, 1, 0, 0, 0, tzinfo=UTC)
    eval_date = datetime(2026, 10, 5, 0, 0, 0, tzinfo=UTC)  # 34 days elapsed (window 30 days is elapsed)

    decision = _create_test_decision(
        db_session, user, biz.id, status="APPROVED", window_days=30, reviewed_at=review_date
    )

    # Case A: 0 observations recorded
    report_zero = DecisionMemoryService.evaluate_decision_outcome(
        db=db_session,
        current_user=user,
        business_id=biz.id,
        decision_id=decision.id,
        as_of=eval_date,
    )
    assert report_zero.is_window_elapsed is True
    assert report_zero.maturity_status == OutcomeMaturityStatus.DUE_INSUFFICIENT
    assert report_zero.coverage_pct == 0.0

    # Case B: Observations only cover 10 out of 30 days (33.3% coverage)
    DecisionMemoryService.record_outcome_observation(
        db=db_session,
        current_user=user,
        business_id=biz.id,
        decision_id=decision.id,
        payload=OutcomeObservationCreateRequest(
            metric_name="revenue",
            unit="USD",
            period_start=review_date,
            period_end=review_date + timedelta(days=10),
            observed_value=3200.0,
            source="pos_sales_stream",
            idempotency_key="obs_partial_10d",
        ),
    )

    report_partial = DecisionMemoryService.evaluate_decision_outcome(
        db=db_session,
        current_user=user,
        business_id=biz.id,
        decision_id=decision.id,
        as_of=eval_date,
    )
    assert report_partial.is_window_elapsed is True
    assert report_partial.maturity_status == OutcomeMaturityStatus.DUE_INSUFFICIENT
    assert report_partial.coverage_pct < 90.0
    assert report_partial.evidence_quality == EvidenceQualityGrade.LOW
    assert "incomplete" in report_partial.evidence_explanation


def test_outcome_maturity_mature_sufficient_and_evidence_grades(db_session: Session, tenant_fixture):
    """Verify MATURE_SUFFICIENT and test deterministic HIGH vs MEDIUM evidence quality rules."""
    user = tenant_fixture["user"]
    biz = tenant_fixture["biz"]

    review_date = datetime(2026, 9, 1, 0, 0, 0, tzinfo=UTC)
    eval_date = datetime(2026, 10, 5, 0, 0, 0, tzinfo=UTC)

    decision = _create_test_decision(
        db_session, user, biz.id, status="APPROVED", window_days=30, reviewed_at=review_date
    )

    # 1. Complete automated coverage: 30 of 30 days covered (100%), verified automated source, no partial flags
    DecisionMemoryService.record_outcome_observation(
        db=db_session,
        current_user=user,
        business_id=biz.id,
        decision_id=decision.id,
        payload=OutcomeObservationCreateRequest(
            metric_name="revenue",
            unit="USD",
            period_start=review_date,
            period_end=review_date + timedelta(days=30),
            observed_value=12400.0,
            source="pos_sales_stream",
            dataset_version="hash_v99",
            coverage_pct=100.0,
            is_partial=False,
            idempotency_key="obs_full_30d",
        ),
    )

    report_high = DecisionMemoryService.evaluate_decision_outcome(
        db=db_session,
        current_user=user,
        business_id=biz.id,
        decision_id=decision.id,
        as_of=eval_date,
    )

    assert report_high.maturity_status == OutcomeMaturityStatus.MATURE_SUFFICIENT
    assert report_high.evidence_quality == EvidenceQualityGrade.HIGH
    assert report_high.coverage_pct >= 95.0
    assert report_high.pre_decision_baseline_value == 10000.0
    assert report_high.post_decision_observed_value == 12400.0
    assert report_high.observed_delta == 2400.0
    assert report_high.observed_pct_change == 24.0

    # 2. Test MEDIUM evidence quality: manual audit source
    decision_med = _create_test_decision(
        db_session, user, biz.id, status="APPROVED", window_days=30, reviewed_at=review_date
    )
    DecisionMemoryService.record_outcome_observation(
        db=db_session,
        current_user=user,
        business_id=biz.id,
        decision_id=decision_med.id,
        payload=OutcomeObservationCreateRequest(
            metric_name="revenue",
            unit="USD",
            period_start=review_date,
            period_end=review_date + timedelta(days=30),
            observed_value=11000.0,
            source="manual_audit",  # Manual provenance downgrades to MEDIUM
            coverage_pct=100.0,
            is_partial=False,
            idempotency_key="obs_manual_source",
        ),
    )

    report_med = DecisionMemoryService.evaluate_decision_outcome(
        db=db_session,
        current_user=user,
        business_id=biz.id,
        decision_id=decision_med.id,
        as_of=eval_date,
    )
    assert report_med.maturity_status == OutcomeMaturityStatus.MATURE_SUFFICIENT
    assert report_med.evidence_quality == EvidenceQualityGrade.MEDIUM
    assert "manual provenance" in report_med.evidence_explanation


# ---------------------------------------------------------------------------
# 5. DEFERRED & REJECTED DECISION LIFECYCLE
# ---------------------------------------------------------------------------

def test_deferred_decision_window_activation(db_session: Session, tenant_fixture):
    """Verify a DEFERRED decision does not start evaluation window until action execution is recorded."""
    user = tenant_fixture["user"]
    biz = tenant_fixture["biz"]

    decision = _create_test_decision(db_session, user, biz.id, status="DEFERRED")

    # Before action execution: window is inactive
    report_initial = DecisionMemoryService.evaluate_decision_outcome(
        db=db_session,
        current_user=user,
        business_id=biz.id,
        decision_id=decision.id,
    )
    assert report_initial.window_started is False
    assert report_initial.maturity_status == OutcomeMaturityStatus.NOT_YET_DUE
    assert "no action execution" in report_initial.evidence_explanation

    # Record action execution with effective date
    action_date = datetime(2026, 9, 10, tzinfo=UTC)
    DecisionMemoryService.record_action_execution(
        db=db_session,
        current_user=user,
        business_id=biz.id,
        decision_id=decision.id,
        payload=OutcomeActionExecutionRequest(
            action_type="ACTION_EXECUTED",
            effective_timestamp=action_date,
            notes="Delayed inventory reorder purchase order released",
            idempotency_key="idemp_action_exec_01",
        ),
    )

    # Now window is active from action_date
    report_active = DecisionMemoryService.evaluate_decision_outcome(
        db=db_session,
        current_user=user,
        business_id=biz.id,
        decision_id=decision.id,
        as_of=action_date + timedelta(days=10),
    )
    assert report_active.window_started is True
    assert report_active.window_start == action_date
    assert report_active.elapsed_days == 10.0


def test_rejected_decision_tracks_observed_status_quo(db_session: Session, tenant_fixture):
    """Verify REJECTED decisions track the observed status quo and disclose that they are not counterfactuals."""
    user = tenant_fixture["user"]
    biz = tenant_fixture["biz"]

    review_date = datetime(2026, 9, 1, tzinfo=UTC)
    decision = _create_test_decision(
        db_session, user, biz.id, status="REJECTED", window_days=30, reviewed_at=review_date
    )

    eval_date = review_date + timedelta(days=32)

    # Record status quo observations
    DecisionMemoryService.record_outcome_observation(
        db=db_session,
        current_user=user,
        business_id=biz.id,
        decision_id=decision.id,
        payload=OutcomeObservationCreateRequest(
            metric_name="revenue",
            unit="USD",
            period_start=review_date,
            period_end=review_date + timedelta(days=30),
            observed_value=9500.0,
            source="pos_sales_stream",
            coverage_pct=100.0,
            idempotency_key="obs_status_quo",
        ),
    )

    report = DecisionMemoryService.evaluate_decision_outcome(
        db=db_session,
        current_user=user,
        business_id=biz.id,
        decision_id=decision.id,
        as_of=eval_date,
    )

    assert report.is_status_quo_monitoring is True
    assert "STATUS QUO MONITORING" in report.evidence_explanation
    assert "NOT a counterfactual outcome" in report.evidence_explanation


# ---------------------------------------------------------------------------
# 6. CAUSAL BOUNDARIES & CONFLICTING EVIDENCE
# ---------------------------------------------------------------------------

def test_causal_attribution_boundaries_and_disclaimer(db_session: Session, tenant_fixture):
    """Verify causal_attribution_claimed is strictly False and standard disclaimer is present."""
    user = tenant_fixture["user"]
    biz = tenant_fixture["biz"]

    decision = _create_test_decision(db_session, user, biz.id, status="APPROVED")
    report = DecisionMemoryService.evaluate_decision_outcome(
        db=db_session, current_user=user, business_id=biz.id, decision_id=decision.id
    )

    # Invariant: NEXUS never claims correlation is causation without an identified causal design
    assert report.causal_attribution_claimed is False
    assert "Pre/post comparison reflects observed empirical association only" in report.causal_disclaimer
    assert "potential confounders" in report.causal_disclaimer


def test_conflicting_or_invalid_evidence_detection(db_session: Session, tenant_fixture):
    """Verify overlapping conflicting observations trigger CONFLICTING_OR_INVALID maturity state."""
    user = tenant_fixture["user"]
    biz = tenant_fixture["biz"]

    review_date = datetime(2026, 9, 1, tzinfo=UTC)
    eval_date = review_date + timedelta(days=35)
    decision = _create_test_decision(
        db_session, user, biz.id, status="APPROVED", window_days=30, reviewed_at=review_date
    )

    # Insert two observations for identical periods with different observed values via raw SQL / bypass
    obs1 = DecisionOutcomeObservation(
        decision_id=decision.id,
        business_id=biz.id,
        organization_id=biz.organization_id,
        metric_name="revenue",
        unit="USD",
        period_start=review_date,
        period_end=review_date + timedelta(days=15),
        observed_value=4000.0,
        source="pos",
        idempotency_key="idemp_c1",
        actor_id=user.id,
    )
    obs2 = DecisionOutcomeObservation(
        decision_id=decision.id,
        business_id=biz.id,
        organization_id=biz.organization_id,
        metric_name="revenue",
        unit="USD",
        period_start=review_date,
        period_end=review_date + timedelta(days=15),
        observed_value=8500.0,  # Highly conflicting!
        source="pos_discrepancy",
        idempotency_key="idemp_c2",
        actor_id=user.id,
    )
    db_session.add_all([obs1, obs2])
    db_session.commit()

    report = DecisionMemoryService.evaluate_decision_outcome(
        db=db_session,
        current_user=user,
        business_id=biz.id,
        decision_id=decision.id,
        as_of=eval_date,
    )
    assert report.maturity_status == OutcomeMaturityStatus.CONFLICTING_OR_INVALID
    assert report.evidence_quality == EvidenceQualityGrade.LOW
    assert "CONFLICTING OR INVALID" in report.evidence_explanation


# ---------------------------------------------------------------------------
# 7. REST API INTEGRATION
# ---------------------------------------------------------------------------

def test_rest_api_outcome_tracking_lifecycle(api_client: TestClient, auth_headers: dict[str, str]):
    """Test full HTTP lifecycle: POST decision -> POST outcome -> GET outcomes -> GET evaluate-outcome."""
    headers = auth_headers

    # 1. Create Decision
    dec_resp = api_client.post(
        "/api/v1/history/decisions",
        headers=headers,
        json={
            "recommendation_text": "Reduce unit price on SKU-REST-01 by 15%",
            "recommendation_type": "PRICE_MARKDOWN",
            "action_target_type": "SKU",
            "action_target_id": "SKU-REST-01",
            "baseline_metrics_snapshot": {
                "window_start": "2026-08-01T00:00:00Z",
                "window_end": "2026-08-31T00:00:00Z",
                "window_days": 30,
                "metrics": {"revenue": 5000.0},
            },
            "outcome_window_days": 30,
        },
    )
    assert dec_resp.status_code == 201
    dec_id = dec_resp.json()["id"]

    # 2. Approve Decision
    appr_resp = api_client.patch(
        f"/api/v1/history/decisions/{dec_id}",
        headers=headers,
        json={"status": "APPROVED", "reviewer_notes": "Authorized 15% promotional cut"},
    )
    assert appr_resp.status_code == 200

    # 3. POST /decisions/{id}/outcomes
    t1 = "2026-09-01T00:00:00Z"
    t2 = "2026-09-15T00:00:00Z"
    obs_resp = api_client.post(
        f"/api/v1/history/decisions/{dec_id}/outcomes",
        headers=headers,
        json={
            "metric_name": "revenue",
            "unit": "USD",
            "period_start": t1,
            "period_end": t2,
            "observed_value": 3100.0,
            "source": "pos_sales_stream",
            "coverage_pct": 100.0,
            "idempotency_key": f"api_obs_key_{dec_id}",
        },
    )
    assert obs_resp.status_code == 201
    obs_data = obs_resp.json()
    assert obs_data["metric_name"] == "revenue"
    assert obs_data["observed_value"] == 3100.0

    # 4. GET /decisions/{id}/outcomes
    list_resp = api_client.get(f"/api/v1/history/decisions/{dec_id}/outcomes", headers=headers)
    assert list_resp.status_code == 200
    observations = list_resp.json()
    assert len(observations) == 1
    assert observations[0]["id"] == obs_data["id"]

    # 5. GET /decisions/{id}/evaluate-outcome
    eval_resp = api_client.get(f"/api/v1/history/decisions/{dec_id}/evaluate-outcome", headers=headers)
    assert eval_resp.status_code == 200
    eval_data = eval_resp.json()
    assert eval_data["decision_id"] == dec_id
    assert eval_data["causal_attribution_claimed"] is False
    assert "causal_disclaimer" in eval_data


# ---------------------------------------------------------------------------
# 8. STAGE 2 AUDIT REGRESSION TESTS
# ---------------------------------------------------------------------------

def test_overlapping_intervals_do_not_double_count_coverage(db_session: Session, tenant_fixture):
    """Verify overlapping intervals merge properly and do not double count coverage."""
    user = tenant_fixture["user"]
    biz = tenant_fixture["biz"]
    review_date = datetime(2026, 9, 1, 0, 0, 0, tzinfo=UTC)
    eval_date = datetime(2026, 10, 5, 0, 0, 0, tzinfo=UTC)

    decision = _create_test_decision(
        db_session, user, biz.id, status="APPROVED", window_days=30, reviewed_at=review_date
    )

    # 3 overlapping intervals: [Day 0, Day 15], [Day 10, Day 25], [Day 20, Day 30]
    # Sum of raw durations = 15 + 15 + 10 = 40 days (133% of 30-day window)
    intervals = [
        (review_date, review_date + timedelta(days=15), 5000.0, "obs_ov_1"),
        (review_date + timedelta(days=10), review_date + timedelta(days=25), 5000.0, "obs_ov_2"),
        (review_date + timedelta(days=20), review_date + timedelta(days=30), 4000.0, "obs_ov_3"),
    ]
    for start, end, val, key in intervals:
        DecisionMemoryService.record_outcome_observation(
            db=db_session,
            current_user=user,
            business_id=biz.id,
            decision_id=decision.id,
            payload=OutcomeObservationCreateRequest(
                metric_name="revenue",
                unit="USD",
                period_start=start,
                period_end=end,
                observed_value=val,
                source="pos_sales_stream",
                dataset_version="v1",
                idempotency_key=key,
            ),
        )

    report = DecisionMemoryService.evaluate_decision_outcome(
        db=db_session,
        current_user=user,
        business_id=biz.id,
        decision_id=decision.id,
        as_of=eval_date,
    )

    # Union is strictly 30 days out of 30 days = 100.0%, capped at 100.0%
    assert report.coverage_pct == 100.0
    assert report.maturity_status == OutcomeMaturityStatus.MATURE_SUFFICIENT
    # Coverage is high, but value aggregation is unavailable due to overlapping periods
    assert report.post_decision_observed_value is None
    assert report.observed_delta is None
    assert any("Value aggregation is unavailable" in r for r in report.evidence_reasons)


def test_duplicate_period_observation_deduplication_in_aggregation(db_session: Session, tenant_fixture):
    """Verify duplicate observations for identical periods do not double count post_decision_observed_value."""
    user = tenant_fixture["user"]
    biz = tenant_fixture["biz"]
    review_date = datetime(2026, 9, 1, 0, 0, 0, tzinfo=UTC)
    eval_date = datetime(2026, 10, 5, 0, 0, 0, tzinfo=UTC)

    decision = _create_test_decision(
        db_session, user, biz.id, status="APPROVED", window_days=30, reviewed_at=review_date
    )

    # Insert two observations for the same period with identical observed_value (different idempotency keys)
    for key in ("obs_dup_1", "obs_dup_2"):
        DecisionMemoryService.record_outcome_observation(
            db=db_session,
            current_user=user,
            business_id=biz.id,
            decision_id=decision.id,
            payload=OutcomeObservationCreateRequest(
                metric_name="revenue",
                unit="USD",
                period_start=review_date,
                period_end=review_date + timedelta(days=30),
                observed_value=12000.0,
                source="pos_sales_stream",
                dataset_version="v1",
                idempotency_key=key,
            ),
        )

    report = DecisionMemoryService.evaluate_decision_outcome(
        db=db_session,
        current_user=user,
        business_id=biz.id,
        decision_id=decision.id,
        as_of=eval_date,
    )

    # Deduplicated post-decision value must be 12000.0, NOT 24000.0
    assert report.post_decision_observed_value == 12000.0
    assert report.observed_delta == 2000.0


def test_client_supplied_coverage_cannot_fake_maturity(db_session: Session, tenant_fixture):
    """Verify client-supplied coverage_pct=100 on a short interval cannot make incomplete evidence appear mature."""
    user = tenant_fixture["user"]
    biz = tenant_fixture["biz"]
    review_date = datetime(2026, 9, 1, 0, 0, 0, tzinfo=UTC)
    eval_date = datetime(2026, 10, 5, 0, 0, 0, tzinfo=UTC)

    decision = _create_test_decision(
        db_session, user, biz.id, status="APPROVED", window_days=30, reviewed_at=review_date
    )

    # Client submits 100% coverage on only 2 days of a 30-day window
    DecisionMemoryService.record_outcome_observation(
        db=db_session,
        current_user=user,
        business_id=biz.id,
        decision_id=decision.id,
        payload=OutcomeObservationCreateRequest(
            metric_name="revenue",
            unit="USD",
            period_start=review_date,
            period_end=review_date + timedelta(days=2),
            observed_value=1500.0,
            source="pos_sales_stream",
            dataset_version="v1",
            coverage_pct=100.0,
            idempotency_key="short_obs",
        ),
    )

    report = DecisionMemoryService.evaluate_decision_outcome(
        db=db_session,
        current_user=user,
        business_id=biz.id,
        decision_id=decision.id,
        as_of=eval_date,
    )

    # Window coverage is 2 / 30 = 6.67%, NOT 100%
    assert report.coverage_pct < 10.0
    assert report.maturity_status == OutcomeMaturityStatus.DUE_INSUFFICIENT
    assert report.evidence_quality == EvidenceQualityGrade.LOW


def test_unit_mismatch_between_baseline_and_observation(db_session: Session, tenant_fixture):
    """Verify unit mismatch between pre-decision baseline (USD) and observation (EUR) triggers CONFLICTING_OR_INVALID."""
    user = tenant_fixture["user"]
    biz = tenant_fixture["biz"]
    review_date = datetime(2026, 9, 1, 0, 0, 0, tzinfo=UTC)
    eval_date = datetime(2026, 10, 5, 0, 0, 0, tzinfo=UTC)

    # Baseline has revenue in USD
    decision = _create_test_decision(
        db_session, user, biz.id, status="APPROVED", window_days=30, reviewed_at=review_date
    )

    # Record observation in EUR (bypassing the same-metric prior check by creating directly)
    obs = DecisionOutcomeObservation(
        decision_id=decision.id,
        business_id=biz.id,
        organization_id=biz.organization_id,
        metric_name="revenue",
        unit="EUR",  # Baseline is USD!
        period_start=review_date,
        period_end=review_date + timedelta(days=30),
        observed_value=11000.0,
        source="pos_sales_stream",
        dataset_version="v1",
        idempotency_key="obs_eur_direct",
        actor_id=user.id,
    )
    db_session.add(obs)
    db_session.commit()

    report = DecisionMemoryService.evaluate_decision_outcome(
        db=db_session,
        current_user=user,
        business_id=biz.id,
        decision_id=decision.id,
        as_of=eval_date,
    )

    assert report.maturity_status == OutcomeMaturityStatus.CONFLICTING_OR_INVALID
    assert report.evidence_quality == EvidenceQualityGrade.LOW
    assert "Unit mismatch" in report.evidence_explanation


def test_unrelated_metrics_evaluated_independently(db_session: Session, tenant_fixture):
    """Verify observations for stockout_days do not satisfy coverage for revenue."""
    user = tenant_fixture["user"]
    biz = tenant_fixture["biz"]
    review_date = datetime(2026, 9, 1, 0, 0, 0, tzinfo=UTC)
    eval_date = datetime(2026, 10, 5, 0, 0, 0, tzinfo=UTC)

    decision = _create_test_decision(
        db_session, user, biz.id, status="APPROVED", window_days=30, reviewed_at=review_date
    )

    # Record full 30 days of stockout_days observations
    DecisionMemoryService.record_outcome_observation(
        db=db_session,
        current_user=user,
        business_id=biz.id,
        decision_id=decision.id,
        payload=OutcomeObservationCreateRequest(
            metric_name="stockout_days",
            unit="days",
            period_start=review_date,
            period_end=review_date + timedelta(days=30),
            observed_value=0.0,
            source="inventory_snapshot",
            dataset_version="v1",
            idempotency_key="obs_stockouts",
        ),
    )

    # Evaluate revenue (which has zero observations)
    report_revenue = DecisionMemoryService.evaluate_decision_outcome(
        db=db_session,
        current_user=user,
        business_id=biz.id,
        decision_id=decision.id,
        metric_name="revenue",
        as_of=eval_date,
    )

    assert report_revenue.metric_name == "revenue"
    assert report_revenue.coverage_pct == 0.0
    assert report_revenue.observation_count == 0
    assert report_revenue.maturity_status == OutcomeMaturityStatus.DUE_INSUFFICIENT


def test_missing_dataset_version_downgrades_to_medium_with_reasons(db_session: Session, tenant_fixture):
    """Verify unversioned dataset prevents HIGH quality and returns explicit reasons."""
    user = tenant_fixture["user"]
    biz = tenant_fixture["biz"]
    review_date = datetime(2026, 9, 1, 0, 0, 0, tzinfo=UTC)
    eval_date = datetime(2026, 10, 5, 0, 0, 0, tzinfo=UTC)

    decision = _create_test_decision(
        db_session, user, biz.id, status="APPROVED", window_days=30, reviewed_at=review_date
    )

    DecisionMemoryService.record_outcome_observation(
        db=db_session,
        current_user=user,
        business_id=biz.id,
        decision_id=decision.id,
        payload=OutcomeObservationCreateRequest(
            metric_name="revenue",
            unit="USD",
            period_start=review_date,
            period_end=review_date + timedelta(days=30),
            observed_value=12500.0,
            source="pos_sales_stream",
            dataset_version=None,  # Missing version!
            idempotency_key="obs_unversioned",
        ),
    )

    report = DecisionMemoryService.evaluate_decision_outcome(
        db=db_session,
        current_user=user,
        business_id=biz.id,
        decision_id=decision.id,
        as_of=eval_date,
    )

    assert report.maturity_status == OutcomeMaturityStatus.MATURE_SUFFICIENT
    assert report.evidence_quality == EvidenceQualityGrade.MEDIUM
    assert any("Dataset version fingerprint is missing" in r for r in report.evidence_reasons)


def test_effective_timestamp_required_in_action_execution(db_session: Session, tenant_fixture):
    """Verify action execution rejects missing effective_timestamp and never silently substitutes now()."""
    user = tenant_fixture["user"]
    biz = tenant_fixture["biz"]

    decision = _create_test_decision(db_session, user, biz.id, status="DEFERRED")

    with pytest.raises(HTTPException) as exc:
        DecisionMemoryService.record_action_execution(
            db=db_session,
            current_user=user,
            business_id=biz.id,
            decision_id=decision.id,
            payload=OutcomeActionExecutionRequest(
                action_type="ACTION_EXECUTED",
                effective_timestamp=None,  # Missing!
                idempotency_key="exec_no_ts",
            ),
        )
    assert exc.value.status_code == 400
    assert "effective_timestamp must be explicitly provided" in exc.value.detail


def test_point_in_time_as_of_lookahead_filtering(db_session: Session, tenant_fixture):
    """Verify point-in-time as_of evaluation excludes future observations."""
    user = tenant_fixture["user"]
    biz = tenant_fixture["biz"]
    review_date = datetime(2026, 9, 1, 0, 0, 0, tzinfo=UTC)

    decision = _create_test_decision(
        db_session, user, biz.id, status="APPROVED", window_days=30, reviewed_at=review_date
    )

    # Observation 1: Days 0 to 10
    DecisionMemoryService.record_outcome_observation(
        db=db_session,
        current_user=user,
        business_id=biz.id,
        decision_id=decision.id,
        payload=OutcomeObservationCreateRequest(
            metric_name="revenue",
            unit="USD",
            period_start=review_date,
            period_end=review_date + timedelta(days=10),
            observed_value=3500.0,
            source="pos_sales_stream",
            dataset_version="v1",
            idempotency_key="obs_day_0_10",
        ),
    )

    # Observation 2: Days 15 to 30 (future observation relative to Day 12)
    DecisionMemoryService.record_outcome_observation(
        db=db_session,
        current_user=user,
        business_id=biz.id,
        decision_id=decision.id,
        payload=OutcomeObservationCreateRequest(
            metric_name="revenue",
            unit="USD",
            period_start=review_date + timedelta(days=15),
            period_end=review_date + timedelta(days=30),
            observed_value=6000.0,
            source="pos_sales_stream",
            dataset_version="v1",
            idempotency_key="obs_day_15_30",
        ),
    )

    # Evaluate as_of Day 12
    eval_as_of = review_date + timedelta(days=12)
    report = DecisionMemoryService.evaluate_decision_outcome(
        db=db_session,
        current_user=user,
        business_id=biz.id,
        decision_id=decision.id,
        as_of=eval_as_of,
    )

    # Only Observation 1 (period_start < eval_as_of) should be included
    assert report.observation_count == 1
    assert report.post_decision_observed_value == 3500.0
    assert report.maturity_status == OutcomeMaturityStatus.NOT_YET_DUE


def test_outcome_observation_immutability_enforced(db_session: Session, tenant_fixture):
    """Verify DecisionOutcomeObservation rejects ORM UPDATE and DELETE operations."""
    from app.models.history import AuditLedgerImmutabilityError

    user = tenant_fixture["user"]
    biz = tenant_fixture["biz"]
    decision = _create_test_decision(db_session, user, biz.id, status="APPROVED")

    obs = DecisionMemoryService.record_outcome_observation(
        db=db_session,
        current_user=user,
        business_id=biz.id,
        decision_id=decision.id,
        payload=OutcomeObservationCreateRequest(
            metric_name="revenue",
            unit="USD",
            period_start=datetime(2026, 9, 1, tzinfo=UTC),
            period_end=datetime(2026, 9, 10, tzinfo=UTC),
            observed_value=2500.0,
            source="pos",
            dataset_version="v1",
            idempotency_key="obs_immut_test",
        ),
    )

    # Attempt mutation
    obs.observed_value = 9999.0
    with pytest.raises(AuditLedgerImmutabilityError) as exc:
        db_session.flush()
    assert "Outcome evidence is strictly immutable" in str(exc.value)
    db_session.rollback()

    # Refetch and attempt deletion
    obs_refetched = db_session.get(DecisionOutcomeObservation, obs.id)
    db_session.delete(obs_refetched)
    with pytest.raises(AuditLedgerImmutabilityError) as exc:
        db_session.flush()
    assert "Outcome evidence is strictly immutable" in str(exc.value)
    db_session.rollback()


def test_aggregation_unavailable_for_monthly_plus_overlapping_weekly_observations(db_session: Session, tenant_fixture):
    """Verify monthly observation plus overlapping weekly observations achieves high coverage but denies value aggregation."""
    user = tenant_fixture["user"]
    biz = tenant_fixture["biz"]
    review_date = datetime(2026, 9, 1, 0, 0, 0, tzinfo=UTC)
    eval_date = datetime(2026, 10, 5, 0, 0, 0, tzinfo=UTC)

    decision = _create_test_decision(
        db_session, user, biz.id, status="APPROVED", window_days=30, reviewed_at=review_date
    )

    # Monthly observation
    DecisionMemoryService.record_outcome_observation(
        db=db_session,
        current_user=user,
        business_id=biz.id,
        decision_id=decision.id,
        payload=OutcomeObservationCreateRequest(
            metric_name="revenue",
            unit="USD",
            period_start=review_date,
            period_end=review_date + timedelta(days=30),
            observed_value=10000.0,
            source="pos_sales_stream",
            dataset_version="v1",
            idempotency_key="monthly_full",
        ),
    )

    # Overlapping weekly observations
    for i, (w_start, w_end, w_val) in enumerate([
        (review_date, review_date + timedelta(days=7), 2500.0),
        (review_date + timedelta(days=7), review_date + timedelta(days=14), 2500.0),
    ]):
        DecisionMemoryService.record_outcome_observation(
            db=db_session,
            current_user=user,
            business_id=biz.id,
            decision_id=decision.id,
            payload=OutcomeObservationCreateRequest(
                metric_name="revenue",
                unit="USD",
                period_start=w_start,
                period_end=w_end,
                observed_value=w_val,
                source="pos_sales_stream",
                dataset_version="v1",
                idempotency_key=f"weekly_obs_{i}",
            ),
        )

    report = DecisionMemoryService.evaluate_decision_outcome(
        db=db_session,
        current_user=user,
        business_id=biz.id,
        decision_id=decision.id,
        as_of=eval_date,
    )

    # 1. Coverage is 100% due to full monthly interval
    assert report.coverage_pct == 100.0
    assert report.maturity_status == OutcomeMaturityStatus.MATURE_SUFFICIENT

    # 2. Value aggregation must NOT silently sum (which would produce 15000.0!)
    assert report.post_decision_observed_value is None
    assert report.observed_delta is None
    assert report.observed_pct_change is None

    # 3. Evidence quality cannot be HIGH when aggregate value is unavailable
    assert report.evidence_quality == EvidenceQualityGrade.MEDIUM
    assert any("Value aggregation is unavailable" in r for r in report.evidence_reasons)


def test_aggregation_unavailable_for_partially_overlapping_periods(db_session: Session, tenant_fixture):
    """Verify partially overlapping periods with different values do not double count and report aggregation unavailable."""
    user = tenant_fixture["user"]
    biz = tenant_fixture["biz"]
    review_date = datetime(2026, 9, 1, 0, 0, 0, tzinfo=UTC)
    eval_date = datetime(2026, 10, 5, 0, 0, 0, tzinfo=UTC)

    decision = _create_test_decision(
        db_session, user, biz.id, status="APPROVED", window_days=30, reviewed_at=review_date
    )

    # Obs 1: Days 0 to 15 = 5000 USD
    DecisionMemoryService.record_outcome_observation(
        db=db_session,
        current_user=user,
        business_id=biz.id,
        decision_id=decision.id,
        payload=OutcomeObservationCreateRequest(
            metric_name="revenue",
            unit="USD",
            period_start=review_date,
            period_end=review_date + timedelta(days=15),
            observed_value=5000.0,
            source="pos_sales_stream",
            dataset_version="v1",
            idempotency_key="partial_ov_1",
        ),
    )

    # Obs 2: Days 10 to 25 = 6000 USD (overlaps on Days 10 to 15)
    DecisionMemoryService.record_outcome_observation(
        db=db_session,
        current_user=user,
        business_id=biz.id,
        decision_id=decision.id,
        payload=OutcomeObservationCreateRequest(
            metric_name="revenue",
            unit="USD",
            period_start=review_date + timedelta(days=10),
            period_end=review_date + timedelta(days=25),
            observed_value=6000.0,
            source="pos_sales_stream",
            dataset_version="v1",
            idempotency_key="partial_ov_2",
        ),
    )

    report = DecisionMemoryService.evaluate_decision_outcome(
        db=db_session,
        current_user=user,
        business_id=biz.id,
        decision_id=decision.id,
        as_of=eval_date,
    )

    # System refuses to sum 5000 + 6000 = 11000 without disaggregation
    assert report.post_decision_observed_value is None
    assert report.observed_delta is None
    assert any("overlapping measurement periods" in r for r in report.evidence_reasons)


def test_aggregation_safe_for_disjoint_periods(db_session: Session, tenant_fixture):
    """Verify strictly disjoint / contiguous periods are safely summed for additive metrics."""
    user = tenant_fixture["user"]
    biz = tenant_fixture["biz"]
    review_date = datetime(2026, 9, 1, 0, 0, 0, tzinfo=UTC)
    eval_date = datetime(2026, 10, 5, 0, 0, 0, tzinfo=UTC)

    decision = _create_test_decision(
        db_session, user, biz.id, status="APPROVED", window_days=30, reviewed_at=review_date
    )

    # 3 strictly disjoint 10-day periods covering 30 days
    slices = [
        (review_date, review_date + timedelta(days=10), 3000.0, "disjoint_1"),
        (review_date + timedelta(days=10), review_date + timedelta(days=20), 4000.0, "disjoint_2"),
        (review_date + timedelta(days=20), review_date + timedelta(days=30), 5500.0, "disjoint_3"),
    ]
    for start, end, val, key in slices:
        DecisionMemoryService.record_outcome_observation(
            db=db_session,
            current_user=user,
            business_id=biz.id,
            decision_id=decision.id,
            payload=OutcomeObservationCreateRequest(
                metric_name="revenue",
                unit="USD",
                period_start=start,
                period_end=end,
                observed_value=val,
                source="pos_sales_stream",
                dataset_version="v1",
                idempotency_key=key,
            ),
        )

    report = DecisionMemoryService.evaluate_decision_outcome(
        db=db_session,
        current_user=user,
        business_id=biz.id,
        decision_id=decision.id,
        as_of=eval_date,
    )

    assert report.coverage_pct == 100.0
    assert report.post_decision_observed_value == 12500.0  # 3000 + 4000 + 5500
    assert report.pre_decision_baseline_value == 10000.0
    assert report.observed_delta == 2500.0
    assert report.observed_pct_change == 25.0
    assert report.evidence_quality == EvidenceQualityGrade.HIGH


def test_conflicting_metric_definitions_across_observations_rejected(db_session: Session, tenant_fixture):
    """Verify observations with contradictory metric definitions in metadata trigger CONFLICTING_OR_INVALID."""
    user = tenant_fixture["user"]
    biz = tenant_fixture["biz"]
    review_date = datetime(2026, 9, 1, 0, 0, 0, tzinfo=UTC)
    eval_date = datetime(2026, 10, 5, 0, 0, 0, tzinfo=UTC)

    decision = _create_test_decision(
        db_session, user, biz.id, status="APPROVED", window_days=30, reviewed_at=review_date
    )

    # Observation 1: defines revenue as gross sales
    DecisionMemoryService.record_outcome_observation(
        db=db_session,
        current_user=user,
        business_id=biz.id,
        decision_id=decision.id,
        payload=OutcomeObservationCreateRequest(
            metric_name="revenue",
            unit="USD",
            period_start=review_date,
            period_end=review_date + timedelta(days=15),
            observed_value=5000.0,
            source="pos_sales_stream",
            dataset_version="v1",
            idempotency_key="obs_def_gross",
            metadata={"metric_definition": "Gross sales before discounts"},
        ),
    )

    # Observation 2: defines revenue as net cash receipts
    DecisionMemoryService.record_outcome_observation(
        db=db_session,
        current_user=user,
        business_id=biz.id,
        decision_id=decision.id,
        payload=OutcomeObservationCreateRequest(
            metric_name="revenue",
            unit="USD",
            period_start=review_date + timedelta(days=15),
            period_end=review_date + timedelta(days=30),
            observed_value=4000.0,
            source="pos_sales_stream",
            dataset_version="v1",
            idempotency_key="obs_def_net",
            metadata={"metric_definition": "Net cash receipts after returns"},
        ),
    )

    report = DecisionMemoryService.evaluate_decision_outcome(
        db=db_session,
        current_user=user,
        business_id=biz.id,
        decision_id=decision.id,
        as_of=eval_date,
    )

    assert report.maturity_status == OutcomeMaturityStatus.CONFLICTING_OR_INVALID
    assert report.evidence_quality == EvidenceQualityGrade.LOW
    assert report.post_decision_observed_value is None
    assert any("Conflicting metric definitions" in r for r in report.evidence_reasons)


def test_metric_definition_mismatch_against_baseline_rejected(db_session: Session, tenant_fixture):
    """Verify observation with metric definition conflicting with baseline snapshot triggers CONFLICTING_OR_INVALID."""
    user = tenant_fixture["user"]
    biz = tenant_fixture["biz"]
    review_date = datetime(2026, 9, 1, 0, 0, 0, tzinfo=UTC)
    eval_date = datetime(2026, 10, 5, 0, 0, 0, tzinfo=UTC)

    # Baseline defines revenue as "Sum of completed orders" (from _create_test_decision)
    decision = _create_test_decision(
        db_session, user, biz.id, status="APPROVED", window_days=30, reviewed_at=review_date
    )

    # Record observation defining revenue as "Estimated projected invoice volume"
    DecisionMemoryService.record_outcome_observation(
        db=db_session,
        current_user=user,
        business_id=biz.id,
        decision_id=decision.id,
        payload=OutcomeObservationCreateRequest(
            metric_name="revenue",
            unit="USD",
            period_start=review_date,
            period_end=review_date + timedelta(days=30),
            observed_value=11000.0,
            source="pos_sales_stream",
            dataset_version="v1",
            idempotency_key="obs_def_incompatible",
            metadata={"metric_definition": "Estimated projected invoice volume"},
        ),
    )

    report = DecisionMemoryService.evaluate_decision_outcome(
        db=db_session,
        current_user=user,
        business_id=biz.id,
        decision_id=decision.id,
        as_of=eval_date,
    )

    assert report.maturity_status == OutcomeMaturityStatus.CONFLICTING_OR_INVALID
    assert report.evidence_quality == EvidenceQualityGrade.LOW
    assert report.post_decision_observed_value is None
    assert any("Metric definition mismatch" in r for r in report.evidence_reasons)
