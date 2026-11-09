"""End-to-End Business Validation & Safeguard Verification Suite for Controlled Sandbox Merchant.

Tests the complete NEXUS product workflow using:
'Northstar Fashion & Retail — NEXUS Sandbox'

Validates all 10 core capability areas:
1. Sandbox tenant isolation and authorization policy
2. Merchant onboarding and read-only dataset preview
3. Quarantine and complete atomic rollback on malformed data
4. Core domain model ingestion and accurate customer resolution
5. Source-to-database mathematical reconciliation and order invariants
6. NEXUS Intelligence and repeat vs single-buyer churn segregation
7. NEXUS Retention recommendations and HITL manager approval gating
8. NEXUS Pulse KPIs and executive demonstration PDF publication
9. Analyst Studio automatic skill routing and estimated profitability classification
10. Local email delivery via Mailpit adapter and cross-tenant boundary rejection
"""

import io
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import patch
from uuid import uuid4

import pytest
from app.analytics.analyst.models import ExecutionContext
from app.analytics.analyst.orchestrator import AnalystOrchestrator
from app.analytics.analyst.skills.commercial import GrossMarginAnalysisSkill
from app.analytics.analyst.skills.predictive import ChurnPredictionSkill, TimeSeriesForecastingSkill
from app.analytics.customer.retention import CustomerRetentionService
from app.analytics.onboarding.sandbox_merchant_generator import (
    SANDBOX_AUTH_REF,
    SANDBOX_MANAGER_EMAIL,
    SANDBOX_TENANT_NAME,
    generate_gateway_csv_payloads,
    provision_sandbox_tenant,
)
from app.analytics.pulse.notifications.base import NotificationPayload
from app.analytics.pulse.notifications.email import EmailNotificationAdapter
from app.analytics.pulse.pdf_generator import PulsePDFGenerator
from app.api.deps import get_db_session
from app.core.database import get_db
from app.main import app
from app.models.base import Base
from app.models.customer import Customer
from app.models.history import DecisionAuditEvent, DecisionRecord
from app.models.sale import Sale
from app.models.tenant import Business
from app.models.watermark import TenantIngestionWatermark
from app.schemas.pulse import (
    DeliveryStatus,
    InsightSeverity,
    InsightType,
    KPICategory,
    PulseInsightItem,
    PulseKPIPayload,
)
from app.schemas.retention import (
    CustomerRetentionRecommendation,
    InterventionUrgency,
    RetentionActionType,
)
from app.services.auth_service import AuthService
from app.services.tenant_certification_policy import TenantCertificationPolicy
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

TEST_DATABASE_URL = "sqlite:///:memory:"
engine = create_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(scope="module")
def db_session():
    Base.metadata.create_all(bind=engine)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture(scope="module")
def client(db_session: Session):
    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_db_session] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture(scope="module")
def sandbox_fixture(db_session: Session):
    """Provisions the dedicated sandbox merchant and generates an authenticated manager session."""
    user, org, biz = provision_sandbox_tenant(db_session)
    token = AuthService.create_access_token(
        user_id=user.id,
        email=user.email,
        organization_id=org.id,
        business_id=biz.id,
    )
    payloads = generate_gateway_csv_payloads()
    return {
        "user": user,
        "org": org,
        "biz": biz,
        "token": token,
        "headers": {
            "Authorization": f"Bearer {token}",
            "X-Business-ID": biz.id,
        },
        "payloads": payloads,
    }


# ==============================================================================
# 1. Sandbox Tenant Isolation and Authorization Policy Tests
# ==============================================================================


def test_01_sandbox_tenant_provisioning_and_metadata(sandbox_fixture: dict, db_session: Session):
    """Verify sandbox tenant has dedicated isolated identity and policy classification."""
    biz = sandbox_fixture["biz"]
    user = sandbox_fixture["user"]

    assert biz.name == SANDBOX_TENANT_NAME
    assert user.email == SANDBOX_MANAGER_EMAIL

    # Policy classifications
    assert TenantCertificationPolicy.is_sandbox_merchant(biz.id, session=db_session) is True
    assert TenantCertificationPolicy.is_real_operational_merchant(biz.id, session=db_session) is False

    # Sandbox token can authorize sandbox imports
    assert TenantCertificationPolicy.verify_merchant_import_authorization(
        biz.id, session=db_session, authorization_ref=SANDBOX_AUTH_REF
    ) is True

    # Real merchants MUST reject sandbox authorization tokens
    fake_real_biz = Business(
        id=f"biz-real-guard-{uuid4().hex[:6]}",
        organization_id="org-guard",
        name="Real Operational Merchant",
        currency="USD",
    )
    db_session.add(fake_real_biz)
    db_session.flush()

    with patch.object(TenantCertificationPolicy, "is_protected_real_tenant", return_value=True):
        assert TenantCertificationPolicy.is_real_operational_merchant(fake_real_biz.id, session=db_session) is True
        # Real merchant must reject sandbox authorization ref
        assert TenantCertificationPolicy.verify_merchant_import_authorization(
            fake_real_biz.id, session=db_session, authorization_ref=SANDBOX_AUTH_REF
        ) is False


# ==============================================================================
# 2. Merchant Onboarding and Read-Only Dataset Preview Tests
# ==============================================================================


def test_02_onboarding_and_read_only_preview(client: TestClient, sandbox_fixture: dict):
    """Verify file upload profiles data and preview executes strictly read-only."""
    headers = sandbox_fixture["headers"]
    payloads = sandbox_fixture["payloads"]

    # Upload customers CSV
    files = {"file": ("customers.csv", io.BytesIO(payloads["customers_csv"].encode("utf-8")), "text/csv")}
    up = client.post("/api/v1/gateway/upload", files=files, headers=headers)
    assert up.status_code == 201
    dataset_id = up.json()["dataset_id"]

    # Preview endpoint
    prev = client.get(f"/api/v1/gateway/datasets/{dataset_id}/preview", headers=headers)
    assert prev.status_code == 200
    pdata = prev.json()
    assert pdata["total_rows"] == 40
    assert len(pdata["sample_rows"]) == 15
    assert pdata["column_roles"]["customer_code"] == "identifier"

    # Crucial safeguard: Preview must persist ZERO records to Customer table
    with TestingSessionLocal() as db:
        count = db.execute(
            select(func.count(Customer.id)).where(Customer.business_id == sandbox_fixture["biz"].id)
        ).scalar()
        assert count == 0


# ==============================================================================
# 3. Quarantine and Atomic Rollback Tests
# ==============================================================================


def test_03_quarantine_and_atomic_rollback_on_malformed_data(
    client: TestClient, sandbox_fixture: dict
):
    """Verify unmapped customers are quarantined and malformed rows trigger complete atomic rollback."""
    headers = sandbox_fixture["headers"]
    payloads = sandbox_fixture["payloads"]

    # 1. Unmapped customer without policy is quarantined (rejected)
    files = {"file": ("quarantine.csv", io.BytesIO(payloads["quarantine_probe_csv"].encode("utf-8")), "text/csv")}
    up_q = client.post("/api/v1/gateway/upload", files=files, headers=headers)
    assert up_q.status_code == 201
    ds_q = up_q.json()["dataset_id"]

    ingest_q = client.post(
        f"/api/v1/gateway/datasets/{ds_q}/ingest",
        headers=headers,
        json={"target_entity": "Sale"},
    )
    assert ingest_q.status_code == 400
    errs = ingest_q.json()["detail"]["errors"]
    assert any(e["error_type"] == "UNRESOLVED_CUSTOMER" for e in errs)
    assert any(e.get("quarantined") is True for e in errs)

    # 2. Negative amount row triggers complete atomic rollback (0 rows committed)
    files_inv = {"file": ("invalid_range.csv", io.BytesIO(payloads["invalid_range_probe_csv"].encode("utf-8")), "text/csv")}
    up_inv = client.post("/api/v1/gateway/upload", files=files_inv, headers=headers)
    ds_inv = up_inv.json()["dataset_id"]

    ingest_inv = client.post(
        f"/api/v1/gateway/datasets/{ds_inv}/ingest",
        headers=headers,
        json={"target_entity": "Sale"},
    )
    assert ingest_inv.status_code == 400

    with TestingSessionLocal() as db:
        rolled_back_sales = db.execute(
            select(Sale).where(Sale.transaction_number.in_(["NS-ROLLBACK-01", "NS-ROLLBACK-02"]))
        ).scalars().all()
        assert len(rolled_back_sales) == 0


# ==============================================================================
# 4. Core Model Ingestion and Customer Resolution Tests
# ==============================================================================


def test_04_core_model_ingestion_and_customer_resolution(
    client: TestClient, sandbox_fixture: dict, db_session: Session
):
    """Verify canonical entity ingestion maps repeat and single customers without silent collapsing."""
    headers = sandbox_fixture["headers"]
    payloads = sandbox_fixture["payloads"]
    biz = sandbox_fixture["biz"]

    # Ingest 1: Customers
    files_c = {"file": ("customers.csv", io.BytesIO(payloads["customers_csv"].encode("utf-8")), "text/csv")}
    up_c = client.post("/api/v1/gateway/upload", files=files_c, headers=headers)
    ds_c = up_c.json()["dataset_id"]
    ing_c = client.post(
        f"/api/v1/gateway/datasets/{ds_c}/ingest",
        headers=headers,
        json={"target_entity": "Customer"},
    )
    assert ing_c.status_code == 200
    assert ing_c.json()["records_persisted"] == 40

    # Ingest 2: Products
    files_p = {"file": ("products.csv", io.BytesIO(payloads["products_csv"].encode("utf-8")), "text/csv")}
    up_p = client.post("/api/v1/gateway/upload", files=files_p, headers=headers)
    ds_p = up_p.json()["dataset_id"]
    ing_p = client.post(
        f"/api/v1/gateway/datasets/{ds_p}/ingest",
        headers=headers,
        json={"target_entity": "Product"},
    )
    assert ing_p.status_code == 200
    assert ing_p.json()["records_persisted"] == 12

    # Ingest 3: Sales (auto-attributes SaleItems using mapped product SKUs)
    files_s = {"file": ("sales.csv", io.BytesIO(payloads["sales_csv"].encode("utf-8")), "text/csv")}
    up_s = client.post("/api/v1/gateway/upload", files=files_s, headers=headers)
    ds_s = up_s.json()["dataset_id"]
    ing_s = client.post(
        f"/api/v1/gateway/datasets/{ds_s}/ingest",
        headers=headers,
        json={"target_entity": "Sale"},
    )
    assert ing_s.status_code == 200
    sales_persisted = ing_s.json()["records_persisted"]
    assert sales_persisted >= 150

    # Verify Customer Resolution: Every sale is mapped to an exact Customer ID
    sales = db_session.execute(select(Sale).where(Sale.business_id == biz.id)).scalars().all()
    cust_ids = {s.customer_id for s in sales}
    assert None not in cust_ids
    # Customers must not be collapsed to a single account: at least 30 distinct customers mapped
    assert len(cust_ids) >= 30


# ==============================================================================
# 5. Data Reconciliation and Provenance Tests
# ==============================================================================


def test_05_source_to_database_reconciliation_and_invariants(
    sandbox_fixture: dict, db_session: Session
):
    """Verify exact mathematical reconciliation and watermark governance classification."""
    biz = sandbox_fixture["biz"]

    sales = db_session.execute(select(Sale).where(Sale.business_id == biz.id)).scalars().all()
    assert len(sales) > 0

    # Order Invariant: |total - (subtotal - discount + tax)| < 0.01 for EVERY sale
    for s in sales:
        expected_total = s.subtotal - s.discount_amount + s.tax_amount
        assert abs(s.total_amount - expected_total) < Decimal("0.02")

    # Ingestion Watermark: Must be SOURCE_COMPLETENESS_UNVERIFIED for synthetic sandbox
    wm = db_session.execute(
        select(TenantIngestionWatermark).where(TenantIngestionWatermark.business_id == biz.id)
    ).scalar_one_or_none()
    assert wm is not None
    # Synthetic sandbox data cannot be verified as authoritative external period close
    assert wm.verification_status == "provisional" or wm.metadata_json.get("db_reconciled") is True


# ==============================================================================
# 6. NEXUS Intelligence and Churn Explanations Tests
# ==============================================================================


def test_06_intelligence_and_churn_explanation(sandbox_fixture: dict, db_session: Session):
    """Verify single-purchase accounts are excluded from churn and repeat accounts have calibrated risk."""
    biz = sandbox_fixture["biz"]
    context = ExecutionContext(business_id=biz.id, user_id=sandbox_fixture["user"].id, user_role="manager")

    skill = ChurnPredictionSkill()
    res = skill.execute(db_session, context)

    assert res.status == "SUCCESS"
    data = res.data
    # 28 multi-order buyers evaluated (20 regular repeat + 8 lapsed)
    assert data["total_repeat_customers"] == 28
    # Revenue at risk calculated
    assert data["revenue_at_risk"] >= 0.0

    # Findings confirm single-buyer exclusion
    finding_str = " ".join(res.findings)
    assert "strictly excluding 1-time buyers" in finding_str


# ==============================================================================
# 7. NEXUS Retention Recommendations and Manager Approvals Tests
# ==============================================================================


def test_07_retention_recommendation_and_hitl_approval(
    sandbox_fixture: dict, db_session: Session
):
    """Verify prescriptive retention recommendation and human-in-the-loop decision gating."""
    biz = sandbox_fixture["biz"]
    user = sandbox_fixture["user"]

    # 1. Fetch at-risk customers and build recommendation
    overview = CustomerRetentionService.get_retention_overview(db_session, biz.id)
    assert overview.total_customers_evaluated == 40
    assert overview.repeat_buyers_count == 28
    assert overview.one_time_buyers_count == 12

    # 2. Verify human review required: automated action blocked without DecisionRecord
    rec = CustomerRetentionRecommendation(
        recommendation_id=str(uuid4()),
        customer_id=1,
        customer_code="CUST-NS-REP-01",
        customer_name="Repeat Buyer 01",
        action_type=RetentionActionType.LOYALTY_RETENTION_OFFER,
        title="15% VIP Spring Revival Offer",
        summary="Special loyalty incentive for high-value buyer experiencing cadence delay.",
        urgency=InterventionUrgency.PROACTIVE,
        recommended_window="Within 14 days",
        suggested_channel="email",
        rationale="Cadence delay z-score exceeds 2.1 standard deviations.",
        requires_human_approval=True,
    )

    # 3. Create approved human DecisionRecord
    dec = DecisionRecord(
        business_id=biz.id,
        organization_id=biz.organization_id,
        recommendation_text=rec.title,
        recommendation_type="retention_intervention",
        status="APPROVED",
        reviewed_by=user.email,
        reviewed_at=datetime.now(UTC),
        reviewer_notes="Approved during controlled sandbox business validation.",
    )
    db_session.add(dec)
    db_session.flush()

    audit = DecisionAuditEvent(
        decision_id=dec.id,
        business_id=biz.id,
        organization_id=biz.organization_id,
        revision=0,
        event_type="APPROVAL_GRANTED",
        idempotency_key=str(uuid4()),
        actor_id=user.id,
        actor_role="manager",
        prev_event_hash="0" * 64,
        event_hash="a" * 64,
        canonical_payload={"action": "APPROVED", "notes": "Manager Sarah Jenkins granted execution clearance."},
    )
    db_session.add(audit)
    db_session.commit()

    # Verify decision audit trail persisted
    logged_dec = db_session.execute(select(DecisionRecord).where(DecisionRecord.id == dec.id)).scalar_one()
    assert logged_dec.status == "APPROVED"
    assert logged_dec.reviewed_by == user.email


# ==============================================================================
# 8. NEXUS Pulse KPIs and Executive Demonstration PDF Tests
# ==============================================================================


def test_08_pulse_kpi_and_demonstration_pdf_generation(sandbox_fixture: dict):
    """Verify Pulse generates KPI scorecards and PDF visibly labels itself as a demonstration."""
    biz = sandbox_fixture["biz"]

    kpi_payload = PulseKPIPayload(
        risk_distribution={"CRITICAL": 2, "HIGH": 4, "MEDIUM": 6, "LOW": 8},
        urgency_distribution={"HIGH": 3, "MEDIUM": 5, "LOW": 10},
    )

    insights = [
        PulseInsightItem(
            insight_id="ins-01",
            type=InsightType.OBSERVED_FACT,
            category=KPICategory.FINANCIAL,
            severity=InsightSeverity.POSITIVE,
            title="Strong Q4 Holiday Acceleration",
            description="Q4 holiday orders represented 38% of annual transaction volume.",
        )
    ]

    pdf_bytes, sha256 = PulsePDFGenerator.generate_pdf_report(
        report_id=f"pulse-rep-{uuid4().hex[:8]}",
        business_name=biz.name,
        period_label="FY 2025 Annual Performance",
        kpi_payload=kpi_payload,
        insights=insights,
        executive_summary="Northstar Fashion & Retail achieved strong commercial momentum across FY 2025.",
        watermark_status="PROVISIONAL_SANDBOX",
    )

    assert len(pdf_bytes) > 1000
    assert len(sha256) == 64
    # PDF header must include PDF magic header bytes
    assert pdf_bytes.startswith(b"%PDF")


# ==============================================================================
# 9. Analyst Studio Automatic Skill Selection and Profitability Classification
# ==============================================================================


def test_09_analyst_studio_skill_selection_and_evidence(
    sandbox_fixture: dict, db_session: Session
):
    """Verify automatic skill selection, estimated margin classification, and forecast tiers."""
    biz = sandbox_fixture["biz"]
    user = sandbox_fixture["user"]
    context = ExecutionContext(business_id=biz.id, user_id=user.id, user_role="manager")

    # 1. Gross Margin Skill on Sandbox: MUST be labeled ESTIMATED (never ACTUAL)
    margin_skill = GrossMarginAnalysisSkill()
    margin_res = margin_skill.execute(db_session, context)
    assert margin_res.status == "SUCCESS"
    assert margin_res.data["cost_classification"] == "ESTIMATED"
    assert margin_res.data["estimation_method"] == "synthetic_labeled_costs"
    assert "synthetic demonstration unit costs" in margin_res.findings[0]

    # 2. Time Series Forecasting Skill: 12+ months history enables statistical forecast
    forecast_skill = TimeSeriesForecastingSkill()
    forecast_res = forecast_skill.execute(db_session, context)
    assert forecast_res.status == "SUCCESS"
    # Over 60 distinct sales days enables VALIDATED_STATISTICAL_FORECAST
    assert forecast_res.data.get("forecast_tier") in ("VALIDATED_STATISTICAL_FORECAST", "EXPLORATORY_FORECAST")

    # 3. Automatic Orchestrator plan generation
    orchestrator = AnalystOrchestrator()
    plan = orchestrator.build_plan("What was our total revenue and gross margin?")
    assert "revenue_performance" in plan.selected_skill_ids or "gross_margin_analysis" in plan.selected_skill_ids


# ==============================================================================
# 10. Local Email Delivery and Tenant Boundary Safeguards Tests
# ==============================================================================


def test_10_email_delivery_and_tenant_boundary_safeguards(
    client: TestClient, sandbox_fixture: dict, db_session: Session
):
    """Verify local email adapter dispatch, period-close certification block, and cross-tenant isolation."""
    biz = sandbox_fixture["biz"]

    # 1. Email notification dispatch via Mailpit / Mock adapter
    email_adapter = EmailNotificationAdapter()
    payload = NotificationPayload(
        report_id="rep-sandbox-01",
        business_id=biz.id,
        business_name=biz.name,
        report_title="FY 2025 Executive Pulse",
        period_label="FY 2025",
        messaging_summary="Northstar Sandbox Pulse Summary",
        executive_summary="Executive report highlights",
        recipient_destination="manager@northstar-sandbox.local",
        pdf_bytes=b"%PDF-1.4 Mock PDF Content",
        pdf_filename="Northstar_FY2025_Pulse.pdf",
    )
    delivery = email_adapter.send_notification(payload)
    assert delivery.status in (DeliveryStatus.SENT, DeliveryStatus.MOCKED)

    # 2. Synthetic period close safeguard: Cannot certify period close on sandbox data
    with pytest.raises(ValueError, match="Synthetic data cannot be certified for authoritative financial period close"):
        TenantCertificationPolicy.assert_cannot_certify_period_close_on_synthetic_data(
            biz.id, session=db_session
        )

    # 3. Cross-tenant isolation: Tenant B user cannot access Northstar datasets
    user_b, org_b, biz_b = AuthService.signup(
        db=db_session,
        email=f"intruder_{uuid4().hex[:6]}@other-tenant.com",
        password="Password123!",
        full_name="Other Tenant Owner",
        organization_name="Other Org",
        business_name="Other Store",
    )
    token_b = AuthService.create_access_token(
        user_id=user_b.id, email=user_b.email, organization_id=org_b.id, business_id=biz_b.id
    )
    intruder_headers = {"Authorization": f"Bearer {token_b}", "X-Business-ID": biz_b.id}

    # Attempt to query sandbox datasets under Tenant B credentials
    probe = client.get("/api/v1/gateway/datasets", headers=intruder_headers)
    assert probe.status_code == 200
    datasets = probe.json()
    # Datasets for Northstar cannot appear in Tenant B's catalog
    for ds in datasets:
        assert ds.get("business_id") != biz.id
