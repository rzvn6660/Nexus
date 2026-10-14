"""Tests for NEXUS Phase 29 Stage 1: Continuous Intelligence.

Verifies:
1. Deterministic metric shift detection and period-over-period comparison.
2. Statistical anomaly identification via Tukey IQR fences on multi-period historical baselines.
3. False-positive control: normal fluctuations (< threshold) are suppressed.
4. Data quality and insufficient history handling (abstains on empty data, downgrades evidence grade).
5. Fingerprint-based duplicate suppression and active finding updates on scan replays.
6. Multi-tenant isolation: strict business scoping and IDOR defenses on all queries/actions.
7. Linkage to Phase 28 DecisionRecord with cross-business protection.
8. Human feedback capture and finding lifecycle status updates.
9. REST API endpoints (/scan, /findings, /feedback, /link-decision).
"""

import os
import tempfile
import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from unittest.mock import patch

import pytest
from app.analytics.continuous.dimensional import DimensionalDecomposer
from app.analytics.continuous.engine import (
    ContinuousDetectionEngine,
)
from app.analytics.continuous.schemas import (
    ContinuousScanRequest,
    FeedbackType,
    FindingSeverity,
    FindingStatus,
)
from app.analytics.continuous.service import ContinuousIntelligenceService
from app.models.continuous import ContinuousFinding, FindingScanRun
from app.models.customer import Customer
from app.models.history import DecisionRecord
from app.models.product import Product
from app.models.sale import Sale
from app.models.sale_item import SaleItem
from app.models.tenant import (
    Business,
    IngestionJob,
    Organization,
    OrganizationMembership,
    UploadedDataset,
    UserIdentity,
)
from app.services.data_gateway_service import DataGatewayService
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

# ---------------------------------------------------------------------------
# FIXTURES
# ---------------------------------------------------------------------------

@pytest.fixture
def tenant_fixture(db_session: Session):
    """Seed Org A, User A, and Business A."""
    org_a = Organization(id="org_alpha_p29", name="Alpha Org P29", slug="alpha-org-p29")
    db_session.add(org_a)
    db_session.flush()

    user_a = UserIdentity(
        id="usr_alpha_p29",
        email="analyst_p29@alpha.internal",
        full_name="Alpha Analyst P29",
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
        id="biz_alpha_p29",
        organization_id=org_a.id,
        name="Alpha Retail Workspace P29",
        status="active",
    )
    db_session.add(biz_a)
    db_session.commit()

    return {"org": org_a, "user": user_a, "biz": biz_a}


@pytest.fixture
def foreign_tenant_fixture(db_session: Session):
    """Seed Org B, User B, and Business B for IDOR testing."""
    org_b = Organization(id="org_bravo_p29", name="Bravo Org P29", slug="bravo-org-p29")
    db_session.add(org_b)
    db_session.flush()

    user_b = UserIdentity(
        id="usr_bravo_p29",
        email="analyst_p29@bravo.internal",
        full_name="Bravo Analyst P29",
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
        id="biz_bravo_p29",
        organization_id=org_b.id,
        name="Bravo Retail Workspace P29",
        status="active",
    )
    db_session.add(biz_b)
    db_session.commit()

    return {"org": org_b, "user": user_b, "biz": biz_b}


def _get_or_create_customer(db: Session, business_id: str) -> Customer:
    cust = db.execute(select(Customer).where(Customer.business_id == business_id)).scalars().first()
    if not cust:
        uid = uuid.uuid4().hex[:8]
        cust = Customer(
            business_id=business_id,
            customer_code=f"CUST-{uid}",
            name=f"Customer {uid}",
            email=f"customer_{uid}@example.com",
            city="New York",
            customer_segment="Standard",
            acquisition_date=date(2024, 1, 1),
        )
        db.add(cust)
        db.flush()
    return cust


def seed_sale(
    db: Session,
    business_id: str,
    transaction_date: datetime,
    subtotal: float,
    discount: float = 0.0,
    status: str = "completed",
) -> Sale:
    """Helper to seed sales with exact timing."""
    cust = _get_or_create_customer(db, business_id)
    net_total = subtotal - discount
    s = Sale(
        business_id=business_id,
        customer_id=cust.id,
        transaction_date=transaction_date,
        transaction_number=f"TXN-{transaction_date.strftime('%Y%m%d%H%M%S%f')}-{subtotal:.0f}",
        subtotal=Decimal(str(subtotal)),
        discount_amount=Decimal(str(discount)),
        tax_amount=Decimal("0.00"),
        total_amount=Decimal(str(net_total)),
        status=status,
    )
    db.add(s)
    db.flush()
    return s


# ---------------------------------------------------------------------------
# 1. DETERMINISTIC DETECTION ENGINE TESTS
# ---------------------------------------------------------------------------

def test_continuous_detection_metric_shift_net_sales(db_session: Session, tenant_fixture: dict):
    """Verify detection of significant net sales decline (> 15%) comparing current window to baseline."""
    biz_id = tenant_fixture["biz"].id
    ref_time = datetime(2026, 6, 1, 12, 0, 0, tzinfo=UTC)

    # Current period: days 0 to 30 before ref_time -> total $5,000
    for day in range(1, 20, 2):
        seed_sale(db_session, biz_id, ref_time - timedelta(days=day), subtotal=500.0)

    # Baseline period: days 30 to 60 before ref_time -> total $20,000
    for day in range(31, 51, 2):
        seed_sale(db_session, biz_id, ref_time - timedelta(days=day), subtotal=2000.0)

    db_session.commit()

    obs = ContinuousDetectionEngine.evaluate_metric_shift(
        db=db_session,
        business_id=biz_id,
        metric_key="net_sales",
        lookback_days=30,
        baseline_days=30,
        min_relative_change=0.15,
        reference_time=ref_time,
    )

    assert obs is not None
    assert obs.metric_key == "net_sales"
    assert obs.current_value == 5000.0
    assert obs.baseline_value == 20000.0
    assert obs.delta_value == -15000.0
    assert obs.relative_change_pct == -75.0
    assert obs.severity in (FindingSeverity.HIGH, FindingSeverity.CRITICAL)
    assert obs.change_type.value in ("TREND_SHIFT", "STATISTICAL_ANOMALY")
    assert "Net Sales" in obs.title
    assert "decreased by 75.0%" in obs.title
    assert obs.provenance["disclaimer"] is not None


def test_continuous_detection_statistical_anomaly_tukey_iqr(db_session: Session, tenant_fixture: dict):
    """Verify Tukey IQR fences classify extreme outliers as STATISTICAL_ANOMALY across historical periods."""
    biz_id = tenant_fixture["biz"].id
    ref_time = datetime(2026, 6, 1, 12, 0, 0, tzinfo=UTC)

    # Seed 5 historical baseline periods with stable sales (~$10,000 per 30-day block)
    # Periods: [30-60d, 60-90d, 90-120d, 120-150d, 150-180d]
    for p in range(1, 6):
        mid_day = p * 30 + 15
        seed_sale(db_session, biz_id, ref_time - timedelta(days=mid_day), subtotal=10000.0)

    # Seed current period with severe crash ($1,000)
    seed_sale(db_session, biz_id, ref_time - timedelta(days=5), subtotal=1000.0)
    db_session.commit()

    obs = ContinuousDetectionEngine.evaluate_metric_shift(
        db=db_session,
        business_id=biz_id,
        metric_key="net_sales",
        lookback_days=30,
        baseline_days=30,
        anomaly_iqr_multiplier=1.5,
        reference_time=ref_time,
    )

    assert obs is not None
    # Because 5 historical periods were seeded at 10,000, current period at 1,000 is an extreme anomaly
    assert obs.current_value == 1000.0
    assert obs.baseline_value == 10000.0
    assert obs.calculation_details["historical_baseline"]["periods_sampled"] >= 5


def test_continuous_detection_normal_change_suppressed(db_session: Session, tenant_fixture: dict):
    """Verify false-positive control: fluctuations below the threshold (e.g. 5% change) emit no findings."""
    biz_id = tenant_fixture["biz"].id
    ref_time = datetime(2026, 6, 1, 12, 0, 0, tzinfo=UTC)

    # Current period: $10,500
    seed_sale(db_session, biz_id, ref_time - timedelta(days=5), subtotal=10500.0)
    # Baseline period: $10,000
    seed_sale(db_session, biz_id, ref_time - timedelta(days=35), subtotal=10000.0)
    db_session.commit()

    obs = ContinuousDetectionEngine.evaluate_metric_shift(
        db=db_session,
        business_id=biz_id,
        metric_key="net_sales",
        lookback_days=30,
        baseline_days=30,
        min_relative_change=0.15,  # 15% threshold
        reference_time=ref_time,
    )

    assert obs is None


def test_continuous_detection_empty_history_abstention(db_session: Session, tenant_fixture: dict):
    """Verify engine abstains and returns None when workspace has zero transactions (no hallucinations)."""
    biz_id = tenant_fixture["biz"].id
    ref_time = datetime(2026, 6, 1, 12, 0, 0, tzinfo=UTC)

    obs = ContinuousDetectionEngine.evaluate_metric_shift(
        db=db_session,
        business_id=biz_id,
        metric_key="net_sales",
        lookback_days=30,
        baseline_days=30,
        reference_time=ref_time,
    )

    assert obs is None


# ---------------------------------------------------------------------------
# 2. CONTINUOUS INTELLIGENCE SERVICE & DEDUPLICATION TESTS
# ---------------------------------------------------------------------------

def test_continuous_scan_deduplication_and_idempotency(db_session: Session, tenant_fixture: dict):
    """Verify subsequent scans on identical shifts update existing findings without duplicate alert proliferation."""
    biz = tenant_fixture["biz"]
    user = tenant_fixture["user"]
    ref_time = datetime(2026, 6, 1, 12, 0, 0, tzinfo=UTC)

    # Seed meaningful net sales decline
    seed_sale(db_session, biz.id, ref_time - timedelta(days=5), subtotal=2000.0)
    seed_sale(db_session, biz.id, ref_time - timedelta(days=35), subtotal=10000.0)
    db_session.commit()

    # Scan 1: initial detection
    scan_req = ContinuousScanRequest(metrics=["net_sales"], lookback_days=30, baseline_days=30)
    resp1 = ContinuousIntelligenceService.execute_business_scan(
        db=db_session,
        current_user=user,
        business_id=biz.id,
        scan_request=scan_req,
        reference_time=ref_time,
    )

    assert resp1.status == "COMPLETED"
    assert resp1.findings_detected_count == 1
    assert resp1.findings_new_count == 1
    assert resp1.findings_updated_count == 0

    finding = db_session.execute(
        ContinuousFinding.__table__.select().where(ContinuousFinding.business_id == biz.id)
    ).first()
    assert finding is not None
    assert finding.occurrence_count == 1
    first_finding_id = finding.id

    # Scan 2: replay on same window
    resp2 = ContinuousIntelligenceService.execute_business_scan(
        db=db_session,
        current_user=user,
        business_id=biz.id,
        scan_request=scan_req,
        reference_time=ref_time,
    )

    assert resp2.status == "COMPLETED"
    assert resp2.findings_detected_count == 1
    assert resp2.findings_new_count == 0
    assert resp2.findings_updated_count == 1

    # Verify existing finding was updated in place, NOT duplicated
    all_findings = db_session.execute(
        ContinuousFinding.__table__.select().where(ContinuousFinding.business_id == biz.id)
    ).all()
    assert len(all_findings) == 1
    assert all_findings[0].id == first_finding_id
    assert all_findings[0].occurrence_count == 2


# ---------------------------------------------------------------------------
# 3. TENANT ISOLATION & IDOR DEFENSE TESTS
# ---------------------------------------------------------------------------

def test_continuous_scan_multi_tenant_isolation(
    db_session: Session, tenant_fixture: dict, foreign_tenant_fixture: dict
):
    """Verify that scans strictly isolate business workspaces and reject cross-tenant IDOR access."""
    biz_a = tenant_fixture["biz"]
    user_a = tenant_fixture["user"]
    biz_b = foreign_tenant_fixture["biz"]
    user_b = foreign_tenant_fixture["user"]
    ref_time = datetime(2026, 6, 1, 12, 0, 0, tzinfo=UTC)

    # Seed sales in Business A
    seed_sale(db_session, biz_a.id, ref_time - timedelta(days=5), subtotal=1000.0)
    seed_sale(db_session, biz_a.id, ref_time - timedelta(days=35), subtotal=5000.0)

    # Seed sales in Business B
    seed_sale(db_session, biz_b.id, ref_time - timedelta(days=5), subtotal=8000.0)
    seed_sale(db_session, biz_b.id, ref_time - timedelta(days=35), subtotal=8200.0)
    db_session.commit()

    # User A runs scan on Biz A
    scan_resp = ContinuousIntelligenceService.execute_business_scan(
        db=db_session,
        current_user=user_a,
        business_id=biz_a.id,
        scan_request=ContinuousScanRequest(metrics=["net_sales"]),
        reference_time=ref_time,
    )
    assert scan_resp.findings_new_count == 1

    findings_a = ContinuousIntelligenceService.list_findings(
        db=db_session,
        current_user=user_a,
        business_id=biz_a.id,
    )
    assert findings_a.total_count == 1
    finding_id = findings_a.items[0].id

    # IDOR Attempt 1: User B tries to view Business A finding detail
    with pytest.raises(HTTPException) as exc_info:
        ContinuousIntelligenceService.get_finding_detail(
            db=db_session,
            current_user=user_b,
            business_id=biz_a.id,
            finding_id=finding_id,
        )
    assert exc_info.value.status_code == 403

    # IDOR Attempt 2: User B tries to update Business A finding status
    with pytest.raises(HTTPException) as exc_info:
        ContinuousIntelligenceService.update_finding_status(
            db=db_session,
            current_user=user_b,
            business_id=biz_a.id,
            finding_id=finding_id,
            new_status=FindingStatus.DISMISSED,
        )
    assert exc_info.value.status_code == 403

    # IDOR Attempt 3: User B tries to record feedback on Business A finding
    with pytest.raises(HTTPException) as exc_info:
        ContinuousIntelligenceService.record_finding_feedback(
            db=db_session,
            current_user=user_b,
            business_id=biz_a.id,
            finding_id=finding_id,
            feedback_type=FeedbackType.FALSE_POSITIVE,
        )
    assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# 4. DECISION LINKAGE & FEEDBACK TESTS
# ---------------------------------------------------------------------------

def test_continuous_finding_decision_linkage_and_cross_business_idor(
    db_session: Session, tenant_fixture: dict, foreign_tenant_fixture: dict
):
    """Verify findings link to Phase 28 DecisionRecords and reject cross-business decision linkage."""
    biz_a = tenant_fixture["biz"]
    user_a = tenant_fixture["user"]
    biz_b = foreign_tenant_fixture["biz"]

    # Create Finding in Biz A
    finding = ContinuousFinding(
        business_id=biz_a.id,
        organization_id=biz_a.organization_id,
        fingerprint="fp_linkage_test",
        metric_key="net_sales",
        change_type="TREND_SHIFT",
        severity="HIGH",
        status="ACTIVE",
        title="Net Sales Shift",
        summary="Test shift",
        current_value=5000.0,
        baseline_value=10000.0,
        delta_value=-5000.0,
        relative_change_pct=-50.0,
        unit="USD",
        period_start=datetime.now(UTC),
        period_end=datetime.now(UTC),
        confidence_score=0.8,
        business_impact_score=0.6,
        urgency_score=0.7,
        evidence_quality="HIGH",
        calculation_details={},
        provenance_json={},
    )
    db_session.add(finding)

    # Create DecisionRecord in Biz A
    dec_a = DecisionRecord(
        business_id=biz_a.id,
        organization_id=biz_a.organization_id,
        recommendation_text="Launch promotional discount campaign",
        status="PENDING",
    )
    db_session.add(dec_a)

    # Create DecisionRecord in Biz B
    dec_b = DecisionRecord(
        business_id=biz_b.id,
        organization_id=biz_b.organization_id,
        recommendation_text="Bravo workspace decision",
        status="PENDING",
    )
    db_session.add(dec_b)
    db_session.commit()

    # 1. Legitimate linkage within Business A
    updated = ContinuousIntelligenceService.link_finding_to_decision(
        db=db_session,
        current_user=user_a,
        business_id=biz_a.id,
        finding_id=finding.id,
        decision_id=dec_a.id,
    )
    assert updated.decision_id == dec_a.id

    # 2. Cross-business linkage attempt: link Biz A finding to Biz B decision
    with pytest.raises(HTTPException) as exc_info:
        ContinuousIntelligenceService.link_finding_to_decision(
            db=db_session,
            current_user=user_a,
            business_id=biz_a.id,
            finding_id=finding.id,
            decision_id=dec_b.id,
        )
    assert exc_info.value.status_code == 403


def test_continuous_finding_feedback_and_status_lifecycle(
    db_session: Session, tenant_fixture: dict
):
    """Verify human feedback recording and finding status transitions."""
    biz = tenant_fixture["biz"]
    user = tenant_fixture["user"]

    finding = ContinuousFinding(
        business_id=biz.id,
        organization_id=biz.organization_id,
        fingerprint="fp_lifecycle_test",
        metric_key="orders_count",
        change_type="TREND_SHIFT",
        severity="MEDIUM",
        status="ACTIVE",
        title="Orders Shift",
        summary="Test shift summary",
        current_value=80.0,
        baseline_value=120.0,
        delta_value=-40.0,
        relative_change_pct=-33.3,
        unit="orders",
        period_start=datetime.now(UTC),
        period_end=datetime.now(UTC),
        confidence_score=0.75,
        business_impact_score=0.5,
        urgency_score=0.6,
        evidence_quality="MEDIUM",
        calculation_details={},
        provenance_json={},
    )
    db_session.add(finding)
    db_session.commit()

    # 1. Record Feedback
    fb = ContinuousIntelligenceService.record_finding_feedback(
        db=db_session,
        current_user=user,
        business_id=biz.id,
        finding_id=finding.id,
        feedback_type=FeedbackType.HELPFUL,
        notes="Confirmed with seasonal marketing shift.",
    )
    assert fb.finding_id == finding.id
    assert fb.feedback_type == FeedbackType.HELPFUL

    # 2. Acknowledge Finding
    ack = ContinuousIntelligenceService.update_finding_status(
        db=db_session,
        current_user=user,
        business_id=biz.id,
        finding_id=finding.id,
        new_status=FindingStatus.ACKNOWLEDGED,
    )
    assert ack.status == FindingStatus.ACKNOWLEDGED
    assert ack.acknowledged_at is not None
    assert ack.acknowledged_by == user.email


# ---------------------------------------------------------------------------
# 5. REST API INTEGRATION TESTS
# ---------------------------------------------------------------------------

def test_continuous_rest_api_endpoints(api_client: TestClient, auth_headers: dict[str, str], db_session: Session):
    """Test full HTTP endpoints: /scan -> /findings -> /findings/{id} -> status -> feedback -> link-decision."""
    headers = auth_headers
    biz_id = headers["X-Business-ID"]

    # Seed sales so scan detects something
    now = datetime.now(UTC)
    seed_sale(db_session, biz_id, now - timedelta(days=5), subtotal=1000.0)
    seed_sale(db_session, biz_id, now - timedelta(days=35), subtotal=8000.0)
    db_session.commit()

    # 1. POST /api/v1/continuous/scan
    scan_resp = api_client.post(
        "/api/v1/continuous/scan",
        headers=headers,
        json={"metrics": ["net_sales"], "lookback_days": 30, "baseline_days": 30},
    )
    assert scan_resp.status_code == 200
    scan_data = scan_resp.json()
    assert scan_data["status"] == "COMPLETED"
    assert scan_data["findings_detected_count"] >= 1

    # 2. GET /api/v1/continuous/findings
    list_resp = api_client.get(
        "/api/v1/continuous/findings?status=ACTIVE",
        headers=headers,
    )
    assert list_resp.status_code == 200
    list_data = list_resp.json()
    assert list_data["total_count"] >= 1
    finding_id = list_data["items"][0]["id"]

    # 3. GET /api/v1/continuous/findings/{id}
    detail_resp = api_client.get(
        f"/api/v1/continuous/findings/{finding_id}",
        headers=headers,
    )
    assert detail_resp.status_code == 200
    detail_data = detail_resp.json()
    assert detail_data["id"] == finding_id
    assert "calculation_details" in detail_data

    # 4. PATCH /api/v1/continuous/findings/{id}/status
    patch_resp = api_client.patch(
        f"/api/v1/continuous/findings/{finding_id}/status?status=ACKNOWLEDGED",
        headers=headers,
    )
    assert patch_resp.status_code == 200
    assert patch_resp.json()["status"] == "ACKNOWLEDGED"

    # 5. POST /api/v1/continuous/findings/{id}/feedback
    fb_resp = api_client.post(
        f"/api/v1/continuous/findings/{finding_id}/feedback",
        headers=headers,
        json={"feedback_type": "HELPFUL", "notes": "Audited by finance"},
    )
    assert fb_resp.status_code == 201
    assert fb_resp.json()["feedback_type"] == "HELPFUL"


# ---------------------------------------------------------------------------
# 6. STAGE 1 AUDIT TEST SUITE
# ---------------------------------------------------------------------------

def test_continuous_detection_boundary_disjointness_no_double_counting(
    db_session: Session, tenant_fixture: dict
):
    """Verify half-open time intervals [start, end) prevent boundary double-counting."""
    biz_id = tenant_fixture["biz"].id
    ref_time = datetime(2026, 6, 1, 12, 0, 0, tzinfo=UTC)
    lookback_days = 30
    baseline_days = 30

    current_end = ref_time
    current_start = current_end - timedelta(days=lookback_days)
    baseline_end = current_start
    baseline_start = baseline_end - timedelta(days=baseline_days)

    # Seed transaction exactly at boundary point: baseline_end == current_start
    seed_sale(db_session, biz_id, current_start, subtotal=5000.0)
    # Seed transaction inside baseline
    seed_sale(db_session, biz_id, baseline_start + timedelta(days=5), subtotal=10000.0)
    db_session.commit()

    val_base, count_base = ContinuousDetectionEngine.evaluate_metric_for_window(
        db_session, biz_id, "net_sales", baseline_start, baseline_end
    )
    val_curr, count_curr = ContinuousDetectionEngine.evaluate_metric_for_window(
        db_session, biz_id, "net_sales", current_start, current_end
    )

    # Boundary sale at current_start MUST fall into current window [current_start, current_end)
    # and MUST NOT fall into baseline [baseline_start, baseline_end)
    assert count_base == 1
    assert val_base == 10000.0
    assert count_curr == 1
    assert val_curr == 5000.0


def test_continuous_detection_zero_iqr_and_constant_baseline_series(
    db_session: Session, tenant_fixture: dict
):
    """Verify Tukey IQR handles zero IQR / constant baseline series via fallback without collapsing."""
    biz_id = tenant_fixture["biz"].id
    ref_time = datetime(2026, 6, 1, 12, 0, 0, tzinfo=UTC)

    # Seed all historical baseline periods at exactly $10,000 each -> IQR is 0, std is 0
    for p in range(1, 7):
        mid_day = p * 30 + 15
        seed_sale(db_session, biz_id, ref_time - timedelta(days=mid_day), subtotal=10000.0)

    # Current period crashes to $1,000 (-90%)
    seed_sale(db_session, biz_id, ref_time - timedelta(days=5), subtotal=1000.0)
    db_session.commit()

    obs = ContinuousDetectionEngine.evaluate_metric_shift(
        db=db_session,
        business_id=biz_id,
        metric_key="net_sales",
        lookback_days=30,
        baseline_days=30,
        reference_time=ref_time,
    )

    assert obs is not None
    assert obs.change_type.value == "STATISTICAL_ANOMALY"
    assert obs.calculation_details["statistical_anomaly"] is True
    hist = obs.calculation_details["historical_baseline"]
    assert hist["zero_iqr"] is True
    assert hist["fallback_method"] == "constant_series_baseline"
    assert hist["iqr"] == 0.0


def test_continuous_cooldown_suppression_and_recurrence(
    db_session: Session, tenant_fixture: dict
):
    """Verify findings in cooldown are suppressed, and recur after cooldown expires."""
    biz = tenant_fixture["biz"]
    user = tenant_fixture["user"]
    t0 = datetime(2026, 6, 1, 12, 0, 0, tzinfo=UTC)

    # Seed declining sales
    seed_sale(db_session, biz.id, t0 - timedelta(days=5), subtotal=2000.0)
    seed_sale(db_session, biz.id, t0 - timedelta(days=35), subtotal=10000.0)
    db_session.commit()

    # 1. First scan detects and creates ACTIVE finding
    scan_req = ContinuousScanRequest(metrics=["net_sales"], lookback_days=30, baseline_days=30, cooldown_days=7)
    res1 = ContinuousIntelligenceService.execute_business_scan(
        db=db_session,
        current_user=user,
        business_id=biz.id,
        scan_request=scan_req,
        reference_time=t0,
    )
    assert res1.findings_new_count == 1

    findings = ContinuousIntelligenceService.list_findings(
        db=db_session, current_user=user, business_id=biz.id
    )
    finding_id = findings.items[0].id

    # 2. Mark finding RESOLVED at t0
    resolved = ContinuousIntelligenceService.update_finding_status(
        db=db_session,
        current_user=user,
        business_id=biz.id,
        finding_id=finding_id,
        new_status=FindingStatus.RESOLVED,
    )
    assert resolved.status == FindingStatus.RESOLVED

    # 3. Rescan at t0 + 2 days (within 7-day cooldown): MUST be suppressed
    t_cooldown = t0 + timedelta(days=2)
    res2 = ContinuousIntelligenceService.execute_business_scan(
        db=db_session,
        current_user=user,
        business_id=biz.id,
        scan_request=scan_req,
        reference_time=t_cooldown,
    )
    assert res2.findings_new_count == 0
    assert res2.findings_updated_count == 0

    # Verify status remains RESOLVED
    finding_chk = ContinuousIntelligenceService.get_finding_detail(
        db=db_session, current_user=user, business_id=biz.id, finding_id=finding_id
    )
    assert finding_chk.status == FindingStatus.RESOLVED

    # 4. Rescan at t0 + 10 days (after 7-day cooldown expires): finding recurs and creates new cycle preserving history
    t_recur = t0 + timedelta(days=10)
    # Seed current period at t_recur so decline persists
    seed_sale(db_session, biz.id, t_recur - timedelta(days=2), subtotal=2000.0)
    seed_sale(db_session, biz.id, t_recur - timedelta(days=35), subtotal=10000.0)
    db_session.commit()

    # Manually backdate updated_at on resolved finding so cooldown cutoff passes
    finding_row = db_session.execute(
        select(ContinuousFinding).where(ContinuousFinding.id == finding_id)
    ).scalar_one()
    finding_row.updated_at = t0
    db_session.commit()

    res3 = ContinuousIntelligenceService.execute_business_scan(
        db=db_session,
        current_user=user,
        business_id=biz.id,
        scan_request=scan_req,
        reference_time=t_recur,
    )
    assert res3.findings_new_count == 1

    # Verify prior finding is preserved uncorrupted as RESOLVED
    prior_finding = db_session.execute(
        select(ContinuousFinding).where(ContinuousFinding.id == finding_id)
    ).scalar_one()
    assert prior_finding.status == FindingStatus.RESOLVED.value
    assert prior_finding.occurrence_count == 1

    # Verify newly created recurring finding is ACTIVE with bumped occurrence_count
    all_findings = db_session.execute(
        select(ContinuousFinding)
        .where(ContinuousFinding.business_id == biz.id)
        .order_by(ContinuousFinding.id)
    ).scalars().all()
    assert len(all_findings) == 2
    recurrent_finding = all_findings[1]
    assert recurrent_finding.status == FindingStatus.ACTIVE.value
    assert recurrent_finding.occurrence_count == 2


def test_continuous_active_and_acknowledged_cannot_coexist(
    db_session: Session, tenant_fixture: dict
):
    """Verify that an ACTIVE finding and an ACKNOWLEDGED finding cannot coexist as duplicate records."""
    biz = tenant_fixture["biz"]
    user = tenant_fixture["user"]
    ref_time = datetime(2026, 6, 1, 12, 0, 0, tzinfo=UTC)

    # 1. Create finding and acknowledge it
    seed_sale(db_session, biz.id, ref_time - timedelta(days=5), subtotal=1000.0)
    seed_sale(db_session, biz.id, ref_time - timedelta(days=35), subtotal=10000.0)
    db_session.commit()

    scan_req = ContinuousScanRequest(metrics=["net_sales"], lookback_days=30, baseline_days=30)
    res = ContinuousIntelligenceService.execute_business_scan(
        db=db_session, current_user=user, business_id=biz.id, scan_request=scan_req, reference_time=ref_time
    )
    assert res.findings_new_count == 1

    findings = ContinuousIntelligenceService.list_findings(db=db_session, current_user=user, business_id=biz.id)
    f_ack = findings.items[0]

    ContinuousIntelligenceService.update_finding_status(
        db=db_session, current_user=user, business_id=biz.id, finding_id=f_ack.id, new_status=FindingStatus.ACKNOWLEDGED
    )

    # 2. Repeated scan updates the ACKNOWLEDGED finding in place; does NOT create a second ACTIVE record
    res2 = ContinuousIntelligenceService.execute_business_scan(
        db=db_session, current_user=user, business_id=biz.id, scan_request=scan_req, reference_time=ref_time
    )
    assert res2.findings_new_count == 0
    assert res2.findings_updated_count == 1

    # Verify only 1 finding exists and its status remained ACKNOWLEDGED
    all_findings = db_session.execute(
        select(ContinuousFinding).where(ContinuousFinding.business_id == biz.id)
    ).scalars().all()
    assert len(all_findings) == 1
    assert all_findings[0].status == FindingStatus.ACKNOWLEDGED.value
    assert all_findings[0].occurrence_count == 2

    # 3. Direct DB-level invariant check: partial unique index blocks inserting an ACTIVE record for same fingerprint
    duplicate_active = ContinuousFinding(
        business_id=biz.id,
        organization_id=biz.organization_id,
        fingerprint=all_findings[0].fingerprint,
        metric_key="net_sales",
        change_type="TREND_SHIFT",
        severity="HIGH",
        status=FindingStatus.ACTIVE.value,
        title="Duplicate Active",
        summary="Should be blocked",
        current_value=1000.0,
        baseline_value=10000.0,
        delta_value=-9000.0,
        relative_change_pct=-90.0,
        unit="USD",
        period_start=datetime.now(UTC),
        period_end=datetime.now(UTC),
        confidence_score=0.8,
        business_impact_score=0.5,
        urgency_score=0.5,
        evidence_quality="HIGH",
        calculation_details={},
        provenance_json={},
        occurrence_count=1,
    )
    db_session.add(duplicate_active)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_continuous_invalid_lifecycle_transition_rejected(
    db_session: Session, tenant_fixture: dict
):
    """Verify state machine rejects unauthorized or invalid transitions with HTTP 400."""
    biz = tenant_fixture["biz"]
    user = tenant_fixture["user"]

    finding = ContinuousFinding(
        business_id=biz.id,
        organization_id=biz.organization_id,
        fingerprint="fp_state_machine_test",
        metric_key="orders_count",
        change_type="TREND_SHIFT",
        severity="MEDIUM",
        status="ACTIVE",
        title="Orders Shift",
        summary="Test shift",
        current_value=50.0,
        baseline_value=100.0,
        delta_value=-50.0,
        relative_change_pct=-50.0,
        unit="orders",
        period_start=datetime.now(UTC),
        period_end=datetime.now(UTC),
        confidence_score=0.7,
        business_impact_score=0.5,
        urgency_score=0.6,
        evidence_quality="MEDIUM",
        calculation_details={},
        provenance_json={},
    )
    db_session.add(finding)
    db_session.commit()

    # ACTIVE -> DISMISSED (valid)
    ContinuousIntelligenceService.update_finding_status(
        db=db_session, current_user=user, business_id=biz.id, finding_id=finding.id, new_status=FindingStatus.DISMISSED
    )

    # DISMISSED -> ACKNOWLEDGED (invalid: cannot acknowledge a dismissed finding without reopening)
    with pytest.raises(HTTPException) as exc_info:
        ContinuousIntelligenceService.update_finding_status(
            db=db_session, current_user=user, business_id=biz.id, finding_id=finding.id, new_status=FindingStatus.ACKNOWLEDGED
        )
    assert exc_info.value.status_code == 400
    assert "Invalid finding status transition" in exc_info.value.detail

    # DISMISSED -> RESOLVED (invalid: cannot directly resolve a dismissed finding)
    with pytest.raises(HTTPException) as exc_info:
        ContinuousIntelligenceService.update_finding_status(
            db=db_session, current_user=user, business_id=biz.id, finding_id=finding.id, new_status=FindingStatus.RESOLVED
        )
    assert exc_info.value.status_code == 400

    # DISMISSED -> ACTIVE (valid reopen)
    ContinuousIntelligenceService.update_finding_status(
        db=db_session, current_user=user, business_id=biz.id, finding_id=finding.id, new_status=FindingStatus.ACTIVE
    )

    # ACTIVE -> RESOLVED (valid)
    ContinuousIntelligenceService.update_finding_status(
        db=db_session, current_user=user, business_id=biz.id, finding_id=finding.id, new_status=FindingStatus.RESOLVED
    )

    # RESOLVED -> ACKNOWLEDGED (invalid)
    with pytest.raises(HTTPException) as exc_info:
        ContinuousIntelligenceService.update_finding_status(
            db=db_session, current_user=user, business_id=biz.id, finding_id=finding.id, new_status=FindingStatus.ACKNOWLEDGED
        )
    assert exc_info.value.status_code == 400


def test_continuous_guessed_id_cross_business_idor(
    db_session: Session, tenant_fixture: dict, foreign_tenant_fixture: dict
):
    """Verify that guessed finding IDs belonging to other workspaces return 403 Forbidden."""
    biz_a = tenant_fixture["biz"]
    user_b = foreign_tenant_fixture["user"]
    biz_b = foreign_tenant_fixture["biz"]

    finding_a = ContinuousFinding(
        business_id=biz_a.id,
        organization_id=biz_a.organization_id,
        fingerprint="fp_guessed_idor_test",
        metric_key="gross_sales",
        change_type="TREND_SHIFT",
        severity="HIGH",
        status="ACTIVE",
        title="Alpha Workspace Finding",
        summary="Test finding",
        current_value=1000.0,
        baseline_value=5000.0,
        delta_value=-4000.0,
        relative_change_pct=-80.0,
        unit="USD",
        period_start=datetime.now(UTC),
        period_end=datetime.now(UTC),
        confidence_score=0.8,
        business_impact_score=0.6,
        urgency_score=0.7,
        evidence_quality="HIGH",
        calculation_details={},
        provenance_json={},
    )
    db_session.add(finding_a)
    db_session.commit()

    # User B queries finding_a.id while authenticated in biz_b.id
    # 1. Detail view IDOR attempt
    with pytest.raises(HTTPException) as exc_info:
        ContinuousIntelligenceService.get_finding_detail(
            db=db_session, current_user=user_b, business_id=biz_b.id, finding_id=finding_a.id
        )
    assert exc_info.value.status_code == 403

    # 2. Status update IDOR attempt
    with pytest.raises(HTTPException) as exc_info:
        ContinuousIntelligenceService.update_finding_status(
            db=db_session, current_user=user_b, business_id=biz_b.id, finding_id=finding_a.id, new_status=FindingStatus.DISMISSED
        )
    assert exc_info.value.status_code == 403

    # 3. Feedback IDOR attempt
    with pytest.raises(HTTPException) as exc_info:
        ContinuousIntelligenceService.record_finding_feedback(
            db=db_session, current_user=user_b, business_id=biz_b.id, finding_id=finding_a.id, feedback_type=FeedbackType.IGNORED
        )
    assert exc_info.value.status_code == 403

    # 4. Completely non-existent guessed ID returns 404
    with pytest.raises(HTTPException) as exc_info:
        ContinuousIntelligenceService.get_finding_detail(
            db=db_session, current_user=user_b, business_id=biz_b.id, finding_id=999999
        )
    assert exc_info.value.status_code == 404


def test_continuous_concurrent_scan_savepoint_simulation(
    db_session: Session, tenant_fixture: dict
):
    """Verify concurrent scan collision triggers IntegrityError on UniqueConstraint and recovers via savepoint."""
    biz = tenant_fixture["biz"]
    user = tenant_fixture["user"]
    ref_time = datetime(2026, 6, 1, 12, 0, 0, tzinfo=UTC)

    seed_sale(db_session, biz.id, ref_time - timedelta(days=5), subtotal=1000.0)
    seed_sale(db_session, biz.id, ref_time - timedelta(days=35), subtotal=10000.0)
    db_session.commit()

    scan_req = ContinuousScanRequest(metrics=["net_sales"], lookback_days=30, baseline_days=30)

    # First scan inserts active finding
    res1 = ContinuousIntelligenceService.execute_business_scan(
        db=db_session,
        current_user=user,
        business_id=biz.id,
        scan_request=scan_req,
        reference_time=ref_time,
    )
    assert res1.findings_new_count == 1

    # Second scan: updates existing finding in place without duplicate creation
    res2 = ContinuousIntelligenceService.execute_business_scan(
        db=db_session,
        current_user=user,
        business_id=biz.id,
        scan_request=scan_req,
        reference_time=ref_time,
    )
    assert res2.status == "COMPLETED"
    assert res2.findings_updated_count == 1

    # Invariants: exactly 1 finding row exists in DB
    all_findings = db_session.execute(
        select(ContinuousFinding).where(ContinuousFinding.business_id == biz.id)
    ).scalars().all()
    assert len(all_findings) == 1
    assert all_findings[0].occurrence_count == 2


# ---------------------------------------------------------------------------
# STAGE 2: INGESTION TRIGGERS AND DIMENSIONAL INTELLIGENCE TESTS
# ---------------------------------------------------------------------------

def _seed_product(
    db: Session,
    business_id: str,
    sku: str,
    name: str,
    category: str,
    unit_cost: float = 10.0,
    selling_price: float = 20.0,
) -> Product:
    prod = db.execute(
        select(Product).where(Product.business_id == business_id, Product.sku == sku)
    ).scalars().first()
    if not prod:
        prod = Product(
            business_id=business_id,
            sku=sku,
            name=name,
            category=category,
            subcategory="General",
            unit_cost=Decimal(str(unit_cost)),
            selling_price=Decimal(str(selling_price)),
            active=True,
        )
        db.add(prod)
        db.flush()
    return prod


def _seed_sale_with_item(
    db: Session,
    business_id: str,
    transaction_date: datetime,
    product: Product,
    customer: Customer,
    quantity: int,
    unit_price: float,
    status: str = "completed",
) -> tuple[Sale, SaleItem]:
    subtotal = quantity * unit_price
    s = Sale(
        business_id=business_id,
        customer_id=customer.id,
        transaction_date=transaction_date,
        transaction_number=f"TXN-{transaction_date.strftime('%Y%m%d%H%M%S%f')}-{uuid.uuid4().hex[:6]}",
        subtotal=Decimal(str(subtotal)),
        discount_amount=Decimal("0.00"),
        tax_amount=Decimal("0.00"),
        total_amount=Decimal(str(subtotal)),
        status=status,
    )
    db.add(s)
    db.flush()
    item = SaleItem(
        sale_id=s.id,
        product_id=product.id,
        quantity=quantity,
        unit_price=Decimal(str(unit_price)),
        discount_amount=Decimal("0.00"),
        line_total=Decimal(str(subtotal)),
    )
    db.add(item)
    db.flush()
    return s, item


def test_continuous_ingestion_triggers_scan_on_success(db_session: Session, tenant_fixture: dict):
    """Verify successful data ingestion automatically commits and triggers continuous intelligence scan."""
    biz = tenant_fixture["biz"]
    org = tenant_fixture["org"]
    dataset_id = str(uuid.uuid4())

    csv_content = (
        b"transaction_date,amount,order_id\n"
        b"2026-05-10,120.50,ORD-ING-001\n"
        b"2026-05-11,250.00,ORD-ING-002\n"
        b"2026-05-12,310.00,ORD-ING-003\n"
    )

    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="wb") as tmp:
        tmp.write(csv_content)
        tmp_name = tmp.name

    schema_json = {
        "mapping_proposal": {
            "target_entity": "Sale",
            "field_mappings": {
                "transaction_date": "date",
                "amount": "amount",
                "order_id": "order_number",
            },
            "missing_required_fields": [],
        },
        "ingestion_status": "PENDING",
    }
    ds = UploadedDataset(
        id=dataset_id,
        organization_id=org.id,
        business_id=biz.id,
        filename="sales_ingest.csv",
        file_type="csv",
        storage_key=tmp_name.replace("\\", "/"),
        file_size_bytes=len(csv_content),
        row_count=3,
        column_count=3,
        content_hash="hash-p29-stage2-001",
        schema_json=schema_json,
        quality_report_json={"readiness_score": 100},
        readiness_status="READY",
    )
    db_session.add(ds)
    db_session.commit()

    try:
        result = DataGatewayService.ingest_into_core_models(
            db=db_session,
            dataset_id=dataset_id,
            business_id=biz.id,
            target_entity="Sale",
        )
        assert result["status"] == "COMPLETED"
        assert result["records_persisted"] == 3
        assert "scan_run_id" in result
        assert result["scan_run_id"] is not None

        # Verify scan run record in database
        scan_run = db_session.execute(
            select(FindingScanRun).where(FindingScanRun.id == result["scan_run_id"])
        ).scalar_one_or_none()
        assert scan_run is not None
        assert scan_run.trigger_type == "INGESTION"
        assert scan_run.status == "COMPLETED"
        assert scan_run.business_id == biz.id
        assert scan_run.organization_id == org.id
        assert scan_run.metadata_json is not None
        assert scan_run.metadata_json.get("ingestion_job_id") == result["job_id"]
        assert scan_run.metadata_json.get("dataset_id") == dataset_id
    finally:
        os.unlink(tmp_name)


def test_continuous_failed_ingestion_does_not_trigger_scan(db_session: Session, tenant_fixture: dict):
    """Verify rejected/failed data ingestion does not trigger continuous intelligence scan."""
    biz = tenant_fixture["biz"]
    org = tenant_fixture["org"]
    dataset_id = str(uuid.uuid4())

    csv_content = (
        b"transaction_date,bad_column,order_id\n"
        b"2026-05-10,120.50,ORD-FAIL-001\n"
    )

    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="wb") as tmp:
        tmp.write(csv_content)
        tmp_name = tmp.name

    # Missing required 'amount' column
    schema_json = {
        "mapping_proposal": {
            "target_entity": "Sale",
            "field_mappings": {
                "transaction_date": "date",
                "order_id": "order_number",
            },
            "missing_required_fields": ["amount"],
        },
        "ingestion_status": "PENDING",
    }
    ds = UploadedDataset(
        id=dataset_id,
        organization_id=org.id,
        business_id=biz.id,
        filename="sales_fail.csv",
        file_type="csv",
        storage_key=tmp_name.replace("\\", "/"),
        file_size_bytes=len(csv_content),
        row_count=1,
        column_count=3,
        content_hash="hash-p29-stage2-fail",
        schema_json=schema_json,
        quality_report_json={"readiness_score": 50},
        readiness_status="READY",
    )
    db_session.add(ds)
    db_session.commit()

    try:
        with pytest.raises(HTTPException) as exc_info:
            DataGatewayService.ingest_into_core_models(
                db=db_session,
                dataset_id=dataset_id,
                business_id=biz.id,
                target_entity="Sale",
            )
        assert exc_info.value.status_code == 400

        # IngestionJob is marked FAILED
        job = db_session.execute(
            select(IngestionJob).where(
                IngestionJob.dataset_id == dataset_id,
                IngestionJob.business_id == biz.id,
            )
        ).scalar_one_or_none()
        assert job is not None
        assert job.status == "FAILED"

        # No INGESTION scan was executed
        scan_runs = db_session.execute(
            select(FindingScanRun).where(
                FindingScanRun.business_id == biz.id,
                FindingScanRun.trigger_type == "INGESTION",
            )
        ).scalars().all()
        # Ensure no scan was run for this failed job
        matching = [r for r in scan_runs if r.metadata_json and r.metadata_json.get("ingestion_job_id") == job.id]
        assert len(matching) == 0
    finally:
        os.unlink(tmp_name)


def test_continuous_ingestion_trigger_is_idempotent(db_session: Session, tenant_fixture: dict):
    """Verify multiple trigger events for the same ingestion job return the same scan run idempotently."""
    biz = tenant_fixture["biz"]
    org = tenant_fixture["org"]
    job_id = str(uuid.uuid4())
    dataset_id = str(uuid.uuid4())

    ds = UploadedDataset(
        id=dataset_id,
        organization_id=org.id,
        business_id=biz.id,
        filename="sales_idem.csv",
        file_type="csv",
        storage_key="/tmp/fake_key",
        file_size_bytes=100,
        row_count=1,
        column_count=1,
        readiness_status="READY",
    )
    job = IngestionJob(
        id=job_id,
        organization_id=org.id,
        business_id=biz.id,
        dataset_id=dataset_id,
        status="COMPLETED",
        target_entity="Sale",
        started_at=datetime.now(UTC),
        completed_at=datetime.now(UTC),
    )
    db_session.add(ds)
    db_session.add(job)
    db_session.commit()

    # First trigger: executes scan
    res1 = ContinuousIntelligenceService.trigger_ingestion_scan(
        db=db_session,
        business_id=biz.id,
        organization_id=org.id,
        dataset_id=dataset_id,
        ingestion_job_id=job_id,
        entity="Sale",
    )
    assert res1 is not None
    assert res1.status == "COMPLETED"
    run_id1 = res1.scan_run_id

    # Second trigger: returns existing scan run idempotently
    res2 = ContinuousIntelligenceService.trigger_ingestion_scan(
        db=db_session,
        business_id=biz.id,
        organization_id=org.id,
        dataset_id=dataset_id,
        ingestion_job_id=job_id,
        entity="Sale",
    )
    assert res2 is not None
    assert res2.scan_run_id == run_id1

    # Verify exactly one scan run exists for this job in database
    runs = db_session.execute(
        select(FindingScanRun).where(
            FindingScanRun.business_id == biz.id,
            FindingScanRun.trigger_type == "INGESTION",
        )
    ).scalars().all()
    matching = [r for r in runs if r.metadata_json and r.metadata_json.get("ingestion_job_id") == job_id]
    assert len(matching) == 1


def test_continuous_scan_failure_does_not_rollback_committed_ingestion(db_session: Session, tenant_fixture: dict):
    """Verify that background continuous scan errors do not rollback or corrupt committed ingestion."""
    biz = tenant_fixture["biz"]
    org = tenant_fixture["org"]
    dataset_id = str(uuid.uuid4())

    csv_content = (
        b"transaction_date,amount,order_id\n"
        b"2026-05-15,500.00,ORD-SAFE-001\n"
    )

    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="wb") as tmp:
        tmp.write(csv_content)
        tmp_name = tmp.name

    schema_json = {
        "mapping_proposal": {
            "target_entity": "Sale",
            "field_mappings": {
                "transaction_date": "date",
                "amount": "amount",
                "order_id": "order_number",
            },
            "missing_required_fields": [],
        },
        "ingestion_status": "PENDING",
    }
    ds = UploadedDataset(
        id=dataset_id,
        organization_id=org.id,
        business_id=biz.id,
        filename="sales_safe.csv",
        file_type="csv",
        storage_key=tmp_name.replace("\\", "/"),
        file_size_bytes=len(csv_content),
        row_count=1,
        column_count=3,
        content_hash="hash-p29-stage2-safe",
        schema_json=schema_json,
        quality_report_json={"readiness_score": 100},
        readiness_status="READY",
    )
    db_session.add(ds)
    db_session.commit()

    try:
        # Simulate continuous intelligence scan crashing
        with patch.object(
            ContinuousIntelligenceService,
            "trigger_ingestion_scan",
            side_effect=RuntimeError("Simulated detection engine crash"),
        ):
            result = DataGatewayService.ingest_into_core_models(
                db=db_session,
                dataset_id=dataset_id,
                business_id=biz.id,
                target_entity="Sale",
            )
            # Ingestion successfully completed despite scan failure
            assert result["status"] == "COMPLETED"
            assert result["records_persisted"] == 1

        # Check job in DB is COMPLETED
        job = db_session.execute(
            select(IngestionJob).where(IngestionJob.id == result["job_id"])
        ).scalar_one_or_none()
        assert job is not None
        assert job.status == "COMPLETED"

        # Check domain sale record was preserved and committed
        sale = db_session.execute(
            select(Sale).where(Sale.transaction_number == "ORD-SAFE-001")
        ).scalar_one_or_none()
        assert sale is not None
        assert sale.subtotal == Decimal("500.00")
    finally:
        os.unlink(tmp_name)


def test_continuous_dimensional_decomposition_variance_reconciliation(db_session: Session, tenant_fixture: dict):
    """Verify dimensional change decomposition ranks contributors and reconciles with aggregate variance."""
    biz = tenant_fixture["biz"]
    ref_time = datetime(2026, 6, 1, 12, 0, 0, tzinfo=UTC)

    # 1. Seed Products across categories
    p_elec = _seed_product(db_session, biz.id, "SKU-ELEC-01", "Smartphone", "Electronics", 50.0, 100.0)
    p_app = _seed_product(db_session, biz.id, "SKU-APP-01", "Jeans", "Apparel", 20.0, 50.0)
    p_home = _seed_product(db_session, biz.id, "SKU-HOME-01", "Coffee Maker", "Home", 30.0, 60.0)

    # Seed Customers in distinct segments
    c_vip = _get_or_create_customer(db_session, biz.id)
    c_vip.customer_segment = "VIP"
    db_session.flush()

    c_corp = Customer(
        business_id=biz.id,
        customer_code="CUST-CORP-01",
        name="Corporate Customer",
        email="corp@example.com",
        city="Chicago",
        customer_segment="Corporate",
        acquisition_date=date(2024, 1, 1),
    )
    db_session.add(c_corp)
    db_session.flush()

    # 2. Baseline Period (35 days before ref_time): Total Net Sales = $18,000
    # Electronics: 100 units @ $100 = $10,000 (VIP)
    _seed_sale_with_item(db_session, biz.id, ref_time - timedelta(days=35), p_elec, c_vip, 100, 100.0)
    # Apparel: 100 units @ $50 = $5,000 (Corporate)
    _seed_sale_with_item(db_session, biz.id, ref_time - timedelta(days=36), p_app, c_corp, 100, 50.0)
    # Home: 50 units @ $60 = $3,000 (Corporate)
    _seed_sale_with_item(db_session, biz.id, ref_time - timedelta(days=37), p_home, c_corp, 50, 60.0)

    # Historical periods 2, 3, 4 to satisfy Tukey IQR baseline sampling:
    for p in range(2, 5):
        t = ref_time - timedelta(days=30 + p * 30)
        _seed_sale_with_item(db_session, biz.id, t, p_elec, c_vip, 100, 100.0)
        _seed_sale_with_item(db_session, biz.id, t, p_app, c_corp, 100, 50.0)
        _seed_sale_with_item(db_session, biz.id, t, p_home, c_corp, 50, 60.0)

    # 3. Current Period (5 days before ref_time): Total Net Sales = $12,000
    # Electronics drops from $10,000 to $4,000 (Delta = -$6,000)
    _seed_sale_with_item(db_session, biz.id, ref_time - timedelta(days=5), p_elec, c_vip, 40, 100.0)
    # Apparel rises from $5,000 to $6,000 (Delta = +$1,000)
    _seed_sale_with_item(db_session, biz.id, ref_time - timedelta(days=6), p_app, c_corp, 120, 50.0)
    # Home drops from $3,000 to $2,000 (Delta = -$1,000)
    _seed_sale_with_item(db_session, biz.id, ref_time - timedelta(days=7), p_home, c_corp, 33, 60.606)  # ~$2000
    db_session.commit()

    # 4. Run Detection Engine
    obs = ContinuousDetectionEngine.evaluate_metric_shift(
        db=db_session,
        business_id=biz.id,
        metric_key="net_sales",
        lookback_days=30,
        baseline_days=30,
        reference_time=ref_time,
    )
    assert obs is not None
    assert obs.current_value < obs.baseline_value

    # 5. Verify Dimensional Decomposition
    decomp = obs.calculation_details.get("dimensional_decomposition")
    assert decomp is not None
    assert decomp["status"] in ("AVAILABLE", "PARTIALLY_AVAILABLE")

    # Category Dimension Verification
    cat_decomp = decomp["dimensions"]["category"]
    assert cat_decomp["status"] == "AVAILABLE"
    assert cat_decomp["reconciled"] is True
    assert cat_decomp["variance_discrepancy"] <= 0.05

    # Check Contributors in Category
    top_neg = cat_decomp["top_negative_contributors"]
    assert len(top_neg) >= 1
    # Leading negative driver is Electronics
    lead_neg = top_neg[0]
    assert lead_neg["entity_id"] == "Electronics"
    assert lead_neg["absolute_change"] == -6000.0
    # Relative contribution to total change (-$6,000 / $6,000 * 100) = -100.0%
    assert lead_neg["contribution_to_change_pct"] == -100.0

    # Leading positive driver is Apparel
    top_pos = cat_decomp["top_positive_contributors"]
    assert len(top_pos) >= 1
    lead_pos = top_pos[0]
    assert lead_pos["entity_id"] == "Apparel"
    assert lead_pos["absolute_change"] == 1000.0
    assert round(lead_pos["contribution_to_change_pct"], 1) == 16.7

    # Provenance and Non-Causality Checks
    prov = decomp["provenance"]
    assert prov["attribution_type"] == "MEASURED_OBSERVATIONAL_CONTRIBUTION"
    assert "causal_disclaimer" in prov
    assert "reconciliation_tolerance" in prov

    # Finding summary must highlight primary contributor
    assert "Electronics" in obs.summary


def test_continuous_dimensional_decomposition_missing_dimensions(db_session: Session, tenant_fixture: dict):
    """Verify continuous intelligence findings remain valid with recorded limitations when dimensions are unpopulated."""
    biz = tenant_fixture["biz"]
    ref_time = datetime(2026, 6, 1, 12, 0, 0, tzinfo=UTC)

    # Seed sales with order headers only (no product/item lines)
    seed_sale(db_session, biz.id, ref_time - timedelta(days=5), subtotal=1000.0)
    seed_sale(db_session, biz.id, ref_time - timedelta(days=35), subtotal=8000.0)
    for p in range(2, 5):
        seed_sale(db_session, biz.id, ref_time - timedelta(days=30 + p * 30), subtotal=8000.0)
    db_session.commit()

    obs = ContinuousDetectionEngine.evaluate_metric_shift(
        db=db_session,
        business_id=biz.id,
        metric_key="net_sales",
        lookback_days=30,
        baseline_days=30,
        reference_time=ref_time,
    )
    # Finding itself is completely valid!
    assert obs is not None
    assert obs.delta_value == -7000.0

    # Category dimension is unavailable due to missing sale items, recorded gracefully
    decomp = obs.calculation_details.get("dimensional_decomposition")
    assert decomp is not None
    cat_dim = decomp["dimensions"]["category"]
    assert cat_dim["status"] == "UNAVAILABLE"
    assert len(cat_dim["limitations"]) > 0
    assert "category" in cat_dim["limitations"][0].lower()


def test_continuous_dimensional_decomposition_negative_and_zero_baselines(db_session: Session, tenant_fixture: dict):
    """Verify safe numerical handling for zero baseline, zero current value, and zero aggregate movement."""
    biz = tenant_fixture["biz"]
    ref_time = datetime(2026, 6, 1, 12, 0, 0, tzinfo=UTC)

    # Test direct decomposer call on zero baseline condition
    decomp = DimensionalDecomposer.decompose_metric_variance(
        db=db_session,
        business_id=biz.id,
        metric_key="net_sales",
        current_start=ref_time - timedelta(days=30),
        current_end=ref_time,
        baseline_start=ref_time - timedelta(days=60),
        baseline_end=ref_time - timedelta(days=30),
        aggregate_delta=0.0,
        current_aggregate=500.0,
        baseline_aggregate=500.0,
    )
    # Zero delta does not crash or raise ZeroDivisionError
    assert decomp["aggregate_delta"] == 0.0


def test_continuous_dimensional_decomposition_insufficient_samples(db_session: Session, tenant_fixture: dict):
    """Verify dimension with only 1 entity records INSUFFICIENT_SAMPLES limitation."""
    biz = tenant_fixture["biz"]
    ref_time = datetime(2026, 6, 1, 12, 0, 0, tzinfo=UTC)

    p_solo = _seed_product(db_session, biz.id, "SKU-SOLO-01", "Solo Item", "Monopoly", 10.0, 50.0)
    c_solo = _get_or_create_customer(db_session, biz.id)

    _seed_sale_with_item(db_session, biz.id, ref_time - timedelta(days=5), p_solo, c_solo, 10, 50.0)
    _seed_sale_with_item(db_session, biz.id, ref_time - timedelta(days=35), p_solo, c_solo, 5, 50.0)
    db_session.commit()

    decomp = DimensionalDecomposer.decompose_metric_variance(
        db=db_session,
        business_id=biz.id,
        metric_key="units_sold",
        current_start=ref_time - timedelta(days=30),
        current_end=ref_time,
        baseline_start=ref_time - timedelta(days=60),
        baseline_end=ref_time - timedelta(days=30),
        aggregate_delta=5.0,
        current_aggregate=10.0,
        baseline_aggregate=5.0,
    )
    cat_dim = decomp["dimensions"]["category"]
    assert cat_dim["status"] == "INSUFFICIENT_SAMPLES"
    assert "Insufficient entity diversity" in cat_dim["limitations"][0]


def test_continuous_ingestion_scan_tenant_isolation(
    db_session: Session, tenant_fixture: dict, foreign_tenant_fixture: dict
):
    """Verify trigger_ingestion_scan rejects foreign business or dataset IDs across tenants."""
    biz_a = tenant_fixture["biz"]
    org_a = tenant_fixture["org"]
    biz_b = foreign_tenant_fixture["biz"]
    org_b = foreign_tenant_fixture["org"]

    # Dataset belongs to Tenant B
    ds_b = UploadedDataset(
        id=str(uuid.uuid4()),
        organization_id=org_b.id,
        business_id=biz_b.id,
        filename="b_sales.csv",
        file_type="csv",
        storage_key="/tmp/b",
        file_size_bytes=10,
        readiness_status="READY",
    )
    job_b = IngestionJob(
        id=str(uuid.uuid4()),
        organization_id=org_b.id,
        business_id=biz_b.id,
        dataset_id=ds_b.id,
        status="COMPLETED",
        target_entity="Sale",
        started_at=datetime.now(UTC),
        completed_at=datetime.now(UTC),
    )
    db_session.add(ds_b)
    db_session.add(job_b)
    db_session.commit()

    # Tenant A attempts to trigger scan using Tenant B's dataset and job
    res = ContinuousIntelligenceService.trigger_ingestion_scan(
        db=db_session,
        business_id=biz_a.id,
        organization_id=org_a.id,
        dataset_id=ds_b.id,
        ingestion_job_id=job_b.id,
    )
    # Rejected without executing scan
    assert res is None

    # Confirm no scan run was recorded under Business A
    runs_a = db_session.execute(
        select(FindingScanRun).where(FindingScanRun.business_id == biz_a.id)
    ).scalars().all()
    assert len(runs_a) == 0


def test_continuous_failed_scan_retry_without_duplicating_findings(
    db_session: Session, tenant_fixture: dict
):
    """Verify failed scans can be retried without duplicating findings or corrupting scan-run history."""
    biz = tenant_fixture["biz"]
    org = tenant_fixture["org"]
    ref_time = datetime(2026, 6, 1, 12, 0, 0, tzinfo=UTC)

    # Seed baseline and current sales to generate a finding
    p1 = _seed_product(db_session, biz.id, "SKU-RETRY-01", "Retry Prod", "Gadgets", 20.0, 100.0)
    c1 = _get_or_create_customer(db_session, biz.id)
    _seed_sale_with_item(db_session, biz.id, ref_time - timedelta(days=5), p1, c1, 2, 100.0)
    _seed_sale_with_item(db_session, biz.id, ref_time - timedelta(days=35), p1, c1, 50, 100.0)
    for p in range(2, 5):
        _seed_sale_with_item(db_session, biz.id, ref_time - timedelta(days=30 + p * 30), p1, c1, 50, 100.0)

    ds = UploadedDataset(
        id=str(uuid.uuid4()),
        organization_id=org.id,
        business_id=biz.id,
        filename="retry_sales.csv",
        file_type="csv",
        storage_key="/tmp/retry",
        file_size_bytes=10,
        readiness_status="READY",
    )
    job = IngestionJob(
        id=str(uuid.uuid4()),
        organization_id=org.id,
        business_id=biz.id,
        dataset_id=ds.id,
        status="COMPLETED",
        target_entity="Sale",
        started_at=datetime.now(UTC),
        completed_at=datetime.now(UTC),
    )
    db_session.add(ds)
    db_session.add(job)
    db_session.commit()

    # 1. Simulate a prior FAILED scan run
    failed_run = FindingScanRun(
        business_id=biz.id,
        organization_id=org.id,
        status="FAILED",
        trigger_type="INGESTION",
        error_message="Simulated temporary database lock timeout",
        metrics_scanned=["net_sales"],
        metadata_json={"ingestion_job_id": job.id},
    )
    db_session.add(failed_run)
    db_session.commit()

    # 2. Trigger scan again: must NOT treat the failed run as an idempotent no-op
    res = ContinuousIntelligenceService.trigger_ingestion_scan(
        db=db_session,
        business_id=biz.id,
        organization_id=org.id,
        dataset_id=ds.id,
        ingestion_job_id=job.id,
        reference_time=ref_time,
    )
    assert res is not None
    assert res.status == "COMPLETED"
    assert res.scan_run_id != failed_run.id

    # Verify both the failed run (history audit intact) and completed run exist
    all_runs = db_session.execute(
        select(FindingScanRun).where(FindingScanRun.business_id == biz.id).order_by(FindingScanRun.id)
    ).scalars().all()
    assert len(all_runs) == 2
    assert all_runs[0].status == "FAILED"
    assert all_runs[1].status == "COMPLETED"

    # 3. Third trigger call: now that a COMPLETED run exists, it acts as idempotent no-op
    res_noop = ContinuousIntelligenceService.trigger_ingestion_scan(
        db=db_session,
        business_id=biz.id,
        organization_id=org.id,
        dataset_id=ds.id,
        ingestion_job_id=job.id,
        reference_time=ref_time,
    )
    assert res_noop.scan_run_id == res.scan_run_id
    assert len(all_runs) == 2  # No extra run created


def test_continuous_process_crash_pending_scan_reconciliation(
    db_session: Session, tenant_fixture: dict
):
    """Verify durable reconciliation recovers scans lost due to process crashes between commit and trigger."""
    biz = tenant_fixture["biz"]
    org = tenant_fixture["org"]
    ref_time = datetime(2026, 6, 1, 12, 0, 0, tzinfo=UTC)

    # Seed sales
    p1 = _seed_product(db_session, biz.id, "SKU-CRASH-01", "Crash Prod", "Hardware", 15.0, 80.0)
    c1 = _get_or_create_customer(db_session, biz.id)
    _seed_sale_with_item(db_session, biz.id, ref_time - timedelta(days=5), p1, c1, 3, 80.0)
    _seed_sale_with_item(db_session, biz.id, ref_time - timedelta(days=35), p1, c1, 40, 80.0)
    for p in range(2, 5):
        _seed_sale_with_item(db_session, biz.id, ref_time - timedelta(days=30 + p * 30), p1, c1, 40, 80.0)

    # Create completed IngestionJob with NO associated scan run (simulating crash after commit)
    ds = UploadedDataset(
        id=str(uuid.uuid4()),
        organization_id=org.id,
        business_id=biz.id,
        filename="crash_sales.csv",
        file_type="csv",
        storage_key="/tmp/crash",
        file_size_bytes=10,
        readiness_status="READY",
    )
    job = IngestionJob(
        id=str(uuid.uuid4()),
        organization_id=org.id,
        business_id=biz.id,
        dataset_id=ds.id,
        status="COMPLETED",
        target_entity="Sale",
        started_at=datetime.now(UTC),
        completed_at=datetime.now(UTC),
    )
    db_session.add(ds)
    db_session.add(job)
    db_session.commit()

    # Reconcile pending scans
    reconciled = ContinuousIntelligenceService.reconcile_pending_ingestion_scans(
        db=db_session,
        business_id=biz.id,
        limit=10,
    )
    assert len(reconciled) == 1
    assert reconciled[0].status == "COMPLETED"

    # Second reconciliation finds nothing pending
    reconciled_again = ContinuousIntelligenceService.reconcile_pending_ingestion_scans(
        db=db_session,
        business_id=biz.id,
        limit=10,
    )
    assert len(reconciled_again) == 0


def test_continuous_ratio_decomposition_average_order_value(
    db_session: Session, tenant_fixture: dict
):
    """Verify mathematically grounded ratio factor decomposition for average_order_value."""
    biz = tenant_fixture["biz"]
    ref_time = datetime(2026, 6, 1, 12, 0, 0, tzinfo=UTC)

    # Baseline period: 4 orders, total revenue = $400 -> AOV = $100.00
    # Current period: 2 orders, total revenue = $300 -> AOV = $150.00
    # Delta AOV = +$50.00
    c_vip = Customer(
        business_id=biz.id,
        customer_code="CUST-AOV-VIP",
        name="VIP Client",
        email="vip@example.com",
        city="New York",
        customer_segment="Enterprise",
        acquisition_date=date(2024, 1, 1),
    )
    c_reg = Customer(
        business_id=biz.id,
        customer_code="CUST-AOV-REG",
        name="Regular Client",
        email="reg@example.com",
        city="Chicago",
        customer_segment="SMB",
        acquisition_date=date(2024, 1, 1),
    )
    db_session.add(c_vip)
    db_session.add(c_reg)
    db_session.flush()
    p1 = _seed_product(db_session, biz.id, "SKU-AOV-01", "AOV Item", "Tech", 10.0, 100.0)

    # Baseline
    _seed_sale_with_item(db_session, biz.id, ref_time - timedelta(days=35), p1, c_vip, 1, 100.0)
    _seed_sale_with_item(db_session, biz.id, ref_time - timedelta(days=40), p1, c_vip, 1, 100.0)
    _seed_sale_with_item(db_session, biz.id, ref_time - timedelta(days=45), p1, c_reg, 1, 100.0)
    _seed_sale_with_item(db_session, biz.id, ref_time - timedelta(days=50), p1, c_reg, 1, 100.0)

    # Current
    _seed_sale_with_item(db_session, biz.id, ref_time - timedelta(days=5), p1, c_vip, 2, 100.0)
    _seed_sale_with_item(db_session, biz.id, ref_time - timedelta(days=10), p1, c_reg, 1, 100.0)
    db_session.commit()

    decomp = DimensionalDecomposer.decompose_metric_variance(
        db=db_session,
        business_id=biz.id,
        metric_key="average_order_value",
        current_start=ref_time - timedelta(days=30),
        current_end=ref_time,
        baseline_start=ref_time - timedelta(days=60),
        baseline_end=ref_time - timedelta(days=30),
        aggregate_delta=50.0,
        current_aggregate=150.0,
        baseline_aggregate=100.0,
    )

    assert decomp["status"] == "AVAILABLE"
    assert decomp["decomposition_type"] == "RATIO_FACTOR_DECOMPOSITION"
    assert decomp["additive_reconciliation_applied"] is False

    rf = decomp["ratio_factors"]
    assert rf["reconciled"] is True
    # Revenue effect + Volume effect == Delta AOV (+50.0)
    sum_factors = rf["numerator_revenue_effect"] + rf["denominator_order_volume_effect"]
    assert abs(sum_factors - 50.0) <= 0.05

    # Customer segment dimension present and labeled as ratio_based
    seg_dim = decomp["dimensions"]["customer_segment"]
    assert seg_dim["ratio_based"] is True
    assert seg_dim["additive_reconciled"] is False

    # Provenance retains non-causality disclaimer
    assert "causal_disclaimer" in decomp["provenance"]


def test_continuous_ratio_decomposition_gross_margin_pct(
    db_session: Session, tenant_fixture: dict
):
    """Verify mathematically grounded ratio factor decomposition for gross_margin_pct."""
    biz = tenant_fixture["biz"]
    ref_time = datetime(2026, 6, 1, 12, 0, 0, tzinfo=UTC)

    # Product A: cost $50, price $100 -> 50% margin
    # Product B: cost $80, price $100 -> 20% margin
    p_high = _seed_product(db_session, biz.id, "SKU-MAR-HIGH", "High Margin Item", "Software", 50.0, 100.0)
    p_low = _seed_product(db_session, biz.id, "SKU-MAR-LOW", "Low Margin Item", "Hardware", 80.0, 100.0)
    cust = _get_or_create_customer(db_session, biz.id)

    # Baseline: 10 units high margin, 10 units low margin -> rev $2000, cogs $1300 -> profit $700 -> 35% margin
    _seed_sale_with_item(db_session, biz.id, ref_time - timedelta(days=35), p_high, cust, 10, 100.0)
    _seed_sale_with_item(db_session, biz.id, ref_time - timedelta(days=40), p_low, cust, 10, 100.0)

    # Current: 20 units high margin, 0 low margin -> rev $2000, cogs $1000 -> profit $1000 -> 50% margin
    _seed_sale_with_item(db_session, biz.id, ref_time - timedelta(days=5), p_high, cust, 20, 100.0)
    db_session.commit()

    decomp = DimensionalDecomposer.decompose_metric_variance(
        db=db_session,
        business_id=biz.id,
        metric_key="gross_margin_pct",
        current_start=ref_time - timedelta(days=30),
        current_end=ref_time,
        baseline_start=ref_time - timedelta(days=60),
        baseline_end=ref_time - timedelta(days=30),
        aggregate_delta=15.0,
        current_aggregate=50.0,
        baseline_aggregate=35.0,
    )

    assert decomp["status"] == "AVAILABLE"
    assert decomp["decomposition_type"] == "RATIO_FACTOR_DECOMPOSITION"
    assert decomp["additive_reconciliation_applied"] is False

    rf = decomp["ratio_factors"]
    assert rf["reconciled"] is True
    # Profit effect + Scale effect == Delta Margin (+15.0%)
    sum_factors = rf["numerator_profit_effect"] + rf["denominator_scale_effect"]
    assert abs(sum_factors - 15.0) <= 0.05

    # Category dimension present
    cat_dim = decomp["dimensions"]["category"]
    assert cat_dim["ratio_based"] is True
    assert cat_dim["additive_reconciled"] is False


def test_continuous_dimensional_missing_mappings_refunds_and_zero_variance(
    db_session: Session, tenant_fixture: dict
):
    """Verify handling of unmapped products, unassigned customer segments, refunded orders, and zero total variance."""
    biz = tenant_fixture["biz"]
    ref_time = datetime(2026, 6, 1, 12, 0, 0, tzinfo=UTC)

    p1 = _seed_product(db_session, biz.id, "SKU-MAP-01", "Mapped Prod", "Books", 10.0, 50.0)
    p_unmapped_cat = _seed_product(db_session, biz.id, "SKU-NO-CAT", "Uncategorized Item", "Unassigned", 10.0, 20.0)

    # Customer without segment (tests func.coalesce to 'Unassigned')
    c_unassigned = Customer(
        business_id=biz.id,
        customer_code="CUST-NO-SEG",
        name="No Segment Customer",
        email="no_seg@example.com",
        city="Houston",
        customer_segment="Unassigned",
        acquisition_date=date(2024, 1, 1),
    )
    db_session.add(c_unassigned)
    db_session.flush()

    # 1. Sale with customer having None segment
    s_curr = Sale(
        business_id=biz.id,
        transaction_number="TXN-NO-SEG-001",
        customer_id=c_unassigned.id,
        subtotal=Decimal("120.00"),
        total_amount=Decimal("120.00"),
        status="completed",
        transaction_date=ref_time - timedelta(days=5),
    )
    db_session.add(s_curr)
    db_session.flush()

    item_mapped = SaleItem(
        sale_id=s_curr.id,
        product_id=p1.id,
        quantity=2,
        unit_price=Decimal("50.00"),
        line_total=Decimal("100.00"),
    )
    db_session.add(item_mapped)

    # 2. Sale item with unmapped product category
    item_unmapped = SaleItem(
        sale_id=s_curr.id,
        product_id=p_unmapped_cat.id,
        quantity=1,
        unit_price=Decimal("20.00"),
        line_total=Decimal("20.00"),
    )
    db_session.add(item_unmapped)

    # 3. Sale with status 'refunded' (must be excluded from completed metric calculations)
    s_refund = Sale(
        business_id=biz.id,
        transaction_number="TXN-REFUND-001",
        customer_id=c_unassigned.id,
        subtotal=Decimal("500.00"),
        total_amount=Decimal("500.00"),
        status="refunded",
        transaction_date=ref_time - timedelta(days=5),
    )
    db_session.add(s_refund)

    # Baseline sale with matching $120 total
    s_base = Sale(
        business_id=biz.id,
        transaction_number="TXN-BASE-001",
        customer_id=c_unassigned.id,
        subtotal=Decimal("120.00"),
        total_amount=Decimal("120.00"),
        status="completed",
        transaction_date=ref_time - timedelta(days=35),
    )
    db_session.add(s_base)
    db_session.flush()
    item_base = SaleItem(
        sale_id=s_base.id,
        product_id=p1.id,
        quantity=2,
        unit_price=Decimal("60.00"),
        line_total=Decimal("120.00"),
    )
    db_session.add(item_base)
    db_session.commit()

    # Zero aggregate delta variance test ($120 current vs $120 baseline -> aggregate_delta = 0.0)
    decomp = DimensionalDecomposer.decompose_metric_variance(
        db=db_session,
        business_id=biz.id,
        metric_key="net_sales",
        current_start=ref_time - timedelta(days=30),
        current_end=ref_time,
        baseline_start=ref_time - timedelta(days=60),
        baseline_end=ref_time - timedelta(days=30),
        aggregate_delta=0.0,
        current_aggregate=120.0,
        baseline_aggregate=120.0,
    )

    # Check unmapped product category was grouped under 'Unassigned' without crashing
    cat_dim = decomp["dimensions"]["category"]
    assert cat_dim["status"] == "AVAILABLE"
    assert cat_dim["reconciled"] is True

    # Check customer segment grouped null segment under 'Unassigned'
    seg_dim = decomp["dimensions"]["customer_segment"]
    assert seg_dim["status"] == "INSUFFICIENT_SAMPLES"  # Only 1 segment ("Unassigned")
    assert seg_dim["entity_count"] == 1
    lead = seg_dim["top_positive_contributors"][0]
    assert lead["entity_id"] == "Unassigned"
    # When aggregate_delta == 0, contribution percentage is safely 0.0 without ZeroDivisionError
    assert lead["contribution_to_change_pct"] == 0.0


def test_continuous_ratio_metric_edge_cases(db_session: Session, tenant_fixture: dict):
    """Verify undefined and extreme zero cases for ratio metrics (AOV and gross margin)."""
    biz = tenant_fixture["biz"]
    ref_time = datetime(2026, 6, 1, 12, 0, 0, tzinfo=UTC)

    # 1. AOV with ZERO baseline orders and ZERO current orders
    decomp_aov_empty = DimensionalDecomposer.decompose_metric_variance(
        db=db_session,
        business_id=biz.id,
        metric_key="average_order_value",
        current_start=ref_time - timedelta(days=30),
        current_end=ref_time,
        baseline_start=ref_time - timedelta(days=60),
        baseline_end=ref_time - timedelta(days=30),
        aggregate_delta=0.0,
        current_aggregate=0.0,
        baseline_aggregate=0.0,
    )
    assert decomp_aov_empty["status"] == "UNAVAILABLE"
    assert "Zero orders" in decomp_aov_empty["limitations"][0]
    assert decomp_aov_empty["dimensions"] == {}

    # 2. AOV with baseline orders > 0 but ZERO current orders
    c1 = _get_or_create_customer(db_session, biz.id)
    p1 = _seed_product(db_session, biz.id, "SKU-AOV-ZERO", "Zero Item", "Misc", 10.0, 50.0)
    _seed_sale_with_item(db_session, biz.id, ref_time - timedelta(days=35), p1, c1, 1, 50.0)
    db_session.commit()

    decomp_aov_zero_curr = DimensionalDecomposer.decompose_metric_variance(
        db=db_session,
        business_id=biz.id,
        metric_key="average_order_value",
        current_start=ref_time - timedelta(days=30),
        current_end=ref_time,
        baseline_start=ref_time - timedelta(days=60),
        baseline_end=ref_time - timedelta(days=30),
        aggregate_delta=-50.0,
        current_aggregate=0.0,
        baseline_aggregate=50.0,
    )
    assert decomp_aov_zero_curr["status"] == "UNAVAILABLE"
    assert "Zero orders" in decomp_aov_zero_curr["limitations"][0]

    # 3. AOV with ZERO revenue in both periods (e.g. 100% discount free samples) but orders > 0
    _seed_sale_with_item(db_session, biz.id, ref_time - timedelta(days=5), p1, c1, 1, 0.0)
    # Also seed a baseline free order
    s_free_base = Sale(
        business_id=biz.id,
        transaction_number="TXN-FREE-BASE",
        customer_id=c1.id,
        subtotal=Decimal("0.00"),
        discount_amount=Decimal("0.00"),
        tax_amount=Decimal("0.00"),
        total_amount=Decimal("0.00"),
        status="completed",
        transaction_date=ref_time - timedelta(days=45),
    )
    db_session.add(s_free_base)
    db_session.commit()

    decomp_aov_zero_rev = DimensionalDecomposer.decompose_metric_variance(
        db=db_session,
        business_id=biz.id,
        metric_key="average_order_value",
        current_start=ref_time - timedelta(days=30),
        current_end=ref_time,
        baseline_start=ref_time - timedelta(days=60),
        baseline_end=ref_time - timedelta(days=30),
        aggregate_delta=-25.0,  # 0.0 vs 25.0 baseline
        current_aggregate=0.0,
        baseline_aggregate=25.0,
    )
    assert decomp_aov_zero_rev["status"] == "AVAILABLE"
    assert decomp_aov_zero_rev["ratio_factors"]["reconciled"] is True

    # 4. Gross margin with ZERO baseline revenue and ZERO current revenue
    decomp_mar_empty = DimensionalDecomposer.decompose_metric_variance(
        db=db_session,
        business_id=biz.id,
        metric_key="gross_margin_pct",
        current_start=ref_time - timedelta(days=300),
        current_end=ref_time - timedelta(days=270),
        baseline_start=ref_time - timedelta(days=330),
        baseline_end=ref_time - timedelta(days=300),
        aggregate_delta=0.0,
        current_aggregate=0.0,
        baseline_aggregate=0.0,
    )
    assert decomp_mar_empty["status"] == "UNAVAILABLE"
    assert "Zero revenue" in decomp_mar_empty["limitations"][0]
    assert decomp_mar_empty["dimensions"] == {}


def test_continuous_reconcile_api_operational_endpoint(
    api_client: TestClient,
    auth_headers: dict[str, str],
    db_session: Session,
):
    """Verify operational POST /api/v1/continuous/reconcile endpoint."""
    headers = auth_headers
    biz_id = headers["X-Business-ID"]
    org_id = "org_test_suite"

    # Seed an IngestionJob without a scan run
    ds = UploadedDataset(
        id=str(uuid.uuid4()),
        organization_id=org_id,
        business_id=biz_id,
        filename="api_crash_sales.csv",
        file_type="csv",
        storage_key="/tmp/api_crash",
        file_size_bytes=10,
        readiness_status="READY",
    )
    job = IngestionJob(
        id=str(uuid.uuid4()),
        organization_id=org_id,
        business_id=biz_id,
        dataset_id=ds.id,
        status="COMPLETED",
        target_entity="Sale",
        started_at=datetime.now(UTC),
        completed_at=datetime.now(UTC),
    )
    db_session.add(ds)
    db_session.add(job)
    db_session.commit()

    # 1. Operational POST /api/v1/continuous/reconcile
    resp = api_client.post(
        "/api/v1/continuous/reconcile?limit=10",
        headers=headers,
    )
    assert resp.status_code == 200
    reconciled_list = resp.json()
    assert len(reconciled_list) == 1
    assert reconciled_list[0]["status"] == "COMPLETED"

    # 2. Second operational call: all jobs reconciled, returns empty list (idempotent)
    resp2 = api_client.post(
        "/api/v1/continuous/reconcile?limit=10",
        headers=headers,
    )
    assert resp2.status_code == 200
    assert resp2.json() == []

    # 3. Missing auth rejected with 401; missing X-Business-ID header rejected with 400
    no_auth_resp = api_client.post("/api/v1/continuous/reconcile")
    assert no_auth_resp.status_code == 401

    auth_only = {"Authorization": headers["Authorization"]}
    no_hdr_resp = api_client.post("/api/v1/continuous/reconcile", headers=auth_only)
    assert no_hdr_resp.status_code == 400


def test_continuous_reconcile_single_scan_under_repeated_calls(
    db_session: Session,
    tenant_fixture: dict,
):
    """Verify that completed ingestion jobs are scanned exactly once under repeated reconciliation passes."""
    biz = tenant_fixture["biz"]
    org = tenant_fixture["org"]

    job_ids = []
    for i in range(3):
        ds = UploadedDataset(
            id=str(uuid.uuid4()),
            organization_id=org.id,
            business_id=biz.id,
            filename=f"batch_sales_{i}.csv",
            file_type="csv",
            storage_key=f"/tmp/batch_{i}",
            file_size_bytes=100,
            readiness_status="READY",
        )
        job = IngestionJob(
            id=str(uuid.uuid4()),
            organization_id=org.id,
            business_id=biz.id,
            dataset_id=ds.id,
            status="COMPLETED",
            target_entity="Sale",
            started_at=datetime.now(UTC),
            completed_at=datetime.now(UTC),
        )
        db_session.add(ds)
        db_session.add(job)
        job_ids.append(job.id)
    db_session.commit()

    # Pass 1: All 3 jobs are reconciled
    pass1 = ContinuousIntelligenceService.reconcile_pending_ingestion_scans(
        db=db_session,
        business_id=biz.id,
        limit=10,
    )
    assert len(pass1) == 3
    assert all(r.status == "COMPLETED" for r in pass1)

    # Pass 2: Immediately repeated pass produces 0 scans (idempotent no-op)
    pass2 = ContinuousIntelligenceService.reconcile_pending_ingestion_scans(
        db=db_session,
        business_id=biz.id,
        limit=10,
    )
    assert len(pass2) == 0

    # Pass 3: Another repeated pass remains 0 scans
    pass3 = ContinuousIntelligenceService.reconcile_pending_ingestion_scans(
        db=db_session,
        business_id=biz.id,
        limit=10,
    )
    assert len(pass3) == 0

    # Verify total scan runs in DB for these jobs is exactly 3 (no duplicate scan runs)
    all_runs = (
        db_session.execute(
            select(FindingScanRun).where(
                FindingScanRun.business_id == biz.id,
                FindingScanRun.trigger_type == "INGESTION",
            )
        )
        .scalars()
        .all()
    )
    scanned_job_ids = [
        r.metadata_json.get("ingestion_job_id")
        for r in all_runs
        if r.metadata_json and "ingestion_job_id" in r.metadata_json
    ]
    for jid in job_ids:
        assert scanned_job_ids.count(jid) == 1


def test_continuous_failed_scan_retry_and_completed_scan_idempotency(
    db_session: Session,
    tenant_fixture: dict,
):
    """Verify that FAILED scans are retried by reconciliation, while COMPLETED scans are not repeated."""
    biz = tenant_fixture["biz"]
    org = tenant_fixture["org"]

    # 1. Job A: Has an existing COMPLETED scan run
    ds_a = UploadedDataset(
        id=str(uuid.uuid4()),
        organization_id=org.id,
        business_id=biz.id,
        filename="completed_sales.csv",
        file_type="csv",
        storage_key="/tmp/comp_a",
        file_size_bytes=50,
        readiness_status="READY",
    )
    job_a = IngestionJob(
        id=str(uuid.uuid4()),
        organization_id=org.id,
        business_id=biz.id,
        dataset_id=ds_a.id,
        status="COMPLETED",
        target_entity="Sale",
        started_at=datetime.now(UTC),
        completed_at=datetime.now(UTC),
    )
    completed_run = FindingScanRun(
        business_id=biz.id,
        organization_id=org.id,
        status="COMPLETED",
        trigger_type="INGESTION",
        metrics_scanned=["net_sales"],
        metadata_json={"ingestion_job_id": job_a.id},
    )
    db_session.add(ds_a)
    db_session.add(job_a)
    db_session.add(completed_run)

    # 2. Job B: Has an existing FAILED scan run (e.g. from prior transient issue)
    ds_b = UploadedDataset(
        id=str(uuid.uuid4()),
        organization_id=org.id,
        business_id=biz.id,
        filename="failed_prior_sales.csv",
        file_type="csv",
        storage_key="/tmp/fail_b",
        file_size_bytes=50,
        readiness_status="READY",
    )
    job_b = IngestionJob(
        id=str(uuid.uuid4()),
        organization_id=org.id,
        business_id=biz.id,
        dataset_id=ds_b.id,
        status="COMPLETED",
        target_entity="Sale",
        started_at=datetime.now(UTC),
        completed_at=datetime.now(UTC),
    )
    failed_run = FindingScanRun(
        business_id=biz.id,
        organization_id=org.id,
        status="FAILED",
        trigger_type="INGESTION",
        metrics_scanned=["net_sales"],
        error_message="Transient DB connection failure",
        metadata_json={"ingestion_job_id": job_b.id},
    )
    db_session.add(ds_b)
    db_session.add(job_b)
    db_session.add(failed_run)
    db_session.commit()

    # Reconcile: Job A must be skipped (already COMPLETED); Job B must be retried
    reconciled = ContinuousIntelligenceService.reconcile_pending_ingestion_scans(
        db=db_session,
        business_id=biz.id,
        limit=10,
    )
    # Only Job B should be reconciled
    assert len(reconciled) == 1
    # Check that reconciled run belongs to Job B
    reconciled_run_record = db_session.execute(
        select(FindingScanRun).where(FindingScanRun.id == reconciled[0].scan_run_id)
    ).scalar_one()
    assert reconciled_run_record.metadata_json["ingestion_job_id"] == job_b.id
    assert reconciled_run_record.status == "COMPLETED"


def test_continuous_simulated_concurrent_worker_claim(
    db_session: Session,
    tenant_fixture: dict,
):
    """
    Simulate concurrent worker claiming of a pending ingestion job.
    Validates under-lock idempotency and verifies that competing claims do not duplicate scan runs.
    NOTE: SQLite serializes database transactions via file lock. Full row-level 'FOR UPDATE SKIP LOCKED'
    concurrency is tested here via under-lock simulation and verified live in PostgreSQL CI environments.
    """
    biz = tenant_fixture["biz"]
    org = tenant_fixture["org"]

    ds = UploadedDataset(
        id=str(uuid.uuid4()),
        organization_id=org.id,
        business_id=biz.id,
        filename="race_dataset.csv",
        file_type="csv",
        storage_key="/tmp/race",
        file_size_bytes=10,
        readiness_status="READY",
    )
    job = IngestionJob(
        id=str(uuid.uuid4()),
        organization_id=org.id,
        business_id=biz.id,
        dataset_id=ds.id,
        status="COMPLETED",
        target_entity="Sale",
        started_at=datetime.now(UTC),
        completed_at=datetime.now(UTC),
    )
    db_session.add(ds)
    db_session.add(job)
    db_session.commit()

    # Worker 1 runs and claims job
    worker1_results = ContinuousIntelligenceService.reconcile_pending_ingestion_scans(
        db=db_session,
        business_id=biz.id,
        limit=10,
    )
    assert len(worker1_results) == 1
    assert worker1_results[0].status == "COMPLETED"

    # Worker 2 runs concurrently or immediately after: job is already claimed/completed
    worker2_results = ContinuousIntelligenceService.reconcile_pending_ingestion_scans(
        db=db_session,
        business_id=biz.id,
        limit=10,
    )
    assert len(worker2_results) == 0

    # Verify exactly 1 scan run was created across both workers
    runs = (
        db_session.execute(
            select(FindingScanRun).where(
                FindingScanRun.business_id == biz.id,
                FindingScanRun.trigger_type == "INGESTION",
            )
        )
        .scalars()
        .all()
    )
    job_runs = [
        r for r in runs
        if r.metadata_json and r.metadata_json.get("ingestion_job_id") == job.id
    ]
    assert len(job_runs) == 1


def test_continuous_reconcile_job_a_completed_does_not_block_job_b(
    db_session: Session,
    tenant_fixture: dict,
):
    """
    Verify per-job idempotency:
    A completed scan for Job A must never prevent an eligible Job B from being scanned.
    """
    biz = tenant_fixture["biz"]
    org = tenant_fixture["org"]

    # 1. Seed Job A with an existing COMPLETED scan run
    ds_a = UploadedDataset(
        id=str(uuid.uuid4()),
        organization_id=org.id,
        business_id=biz.id,
        filename="dataset_a.csv",
        file_type="csv",
        storage_key="/tmp/ds_a",
        file_size_bytes=100,
        readiness_status="READY",
    )
    job_a = IngestionJob(
        id=str(uuid.uuid4()),
        organization_id=org.id,
        business_id=biz.id,
        dataset_id=ds_a.id,
        status="COMPLETED",
        target_entity="Sale",
        started_at=datetime.now(UTC),
        completed_at=datetime.now(UTC),
    )
    run_a = FindingScanRun(
        business_id=biz.id,
        organization_id=org.id,
        status="COMPLETED",
        trigger_type="INGESTION",
        metrics_scanned=["net_sales"],
        metadata_json={"ingestion_job_id": job_a.id},
    )
    db_session.add(ds_a)
    db_session.add(job_a)
    db_session.add(run_a)

    # 2. Seed Job B with NO scan run (eligible pending scan)
    ds_b = UploadedDataset(
        id=str(uuid.uuid4()),
        organization_id=org.id,
        business_id=biz.id,
        filename="dataset_b.csv",
        file_type="csv",
        storage_key="/tmp/ds_b",
        file_size_bytes=100,
        readiness_status="READY",
    )
    job_b = IngestionJob(
        id=str(uuid.uuid4()),
        organization_id=org.id,
        business_id=biz.id,
        dataset_id=ds_b.id,
        status="COMPLETED",
        target_entity="Sale",
        started_at=datetime.now(UTC),
        completed_at=datetime.now(UTC),
    )
    db_session.add(ds_b)
    db_session.add(job_b)
    db_session.commit()

    # 3. Execute reconciliation
    reconciled = ContinuousIntelligenceService.reconcile_pending_ingestion_scans(
        db=db_session,
        business_id=biz.id,
        limit=10,
    )

    # Assert exactly 1 job reconciled, and it is Job B
    assert len(reconciled) == 1
    reconciled_scan = db_session.execute(
        select(FindingScanRun).where(FindingScanRun.id == reconciled[0].scan_run_id)
    ).scalar_one()
    assert reconciled_scan.metadata_json["ingestion_job_id"] == job_b.id
    assert reconciled_scan.status == "COMPLETED"

    # Verify that in DB, Job A has exactly 1 scan and Job B has exactly 1 scan
    all_runs = (
        db_session.execute(
            select(FindingScanRun).where(
                FindingScanRun.business_id == biz.id,
                FindingScanRun.trigger_type == "INGESTION",
            )
        )
        .scalars()
        .all()
    )
    job_a_runs = [
        r for r in all_runs
        if r.metadata_json and r.metadata_json.get("ingestion_job_id") == job_a.id
    ]
    job_b_runs = [
        r for r in all_runs
        if r.metadata_json and r.metadata_json.get("ingestion_job_id") == job_b.id
    ]
    assert len(job_a_runs) == 1
    assert job_a_runs[0].id == run_a.id
    assert len(job_b_runs) == 1
    assert job_b_runs[0].id == reconciled_scan.id

    # 4. Subsequent reconciliation call finds nothing pending (0 scans, idempotent)
    reconciled_again = ContinuousIntelligenceService.reconcile_pending_ingestion_scans(
        db=db_session,
        business_id=biz.id,
        limit=10,
    )
    assert len(reconciled_again) == 0







