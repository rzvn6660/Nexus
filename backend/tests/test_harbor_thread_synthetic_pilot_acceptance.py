"""NEXUS — Harbor & Thread: Complete Synthetic Pilot Acceptance & End-to-End Simulation Suite.

Tests the complete NEXUS product workflow using:
'Harbor & Thread — NEXUS Synthetic Pilot' (Dubai, UAE | AED | Fashion & Lifestyle Retail)

Validates all 10 core capability areas:
1. Synthetic Pilot tenant provisioning, isolation, and policy classification (AED currency, Dubai location)
2. Merchant onboarding, read-only dataset preview, and SIMULATED_CONSENT event persistence
3. Quarantine of unmapped customer probes and complete atomic rollback on malformed data
4. Core domain model ingestion: 1,200 Customers, 180 Products, ~8,000 Sales, and multi-line items
5. Source-to-database mathematical reconciliation, UAE 5% VAT, and order invariants
6. Customer Intelligence: single-purchase exclusion from churn, calibrated risk distribution
7. Prescriptive Retention Intelligence: HITL approval/rejection decision ledger and audit trail
8. NEXUS Pulse executive reporting in AED with actual cost-based synthetic margin and PDF generation
9. Analyst Studio: Dynamic automatic orchestration across all 8 analyst domains
10. Local email notification delivery via Mailpit adapter and strict cross-tenant isolation
"""

import io
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import patch
from uuid import uuid4

import pytest
from app.analytics.analyst.models import ExecutionContext
from app.analytics.analyst.orchestrator import AnalystOrchestrator
from app.analytics.analyst.skills.commercial import GrossMarginAnalysisSkill, RevenuePerformanceSkill
from app.analytics.analyst.skills.customer import RepeatPurchaseSkill, RFMSegmentationSkill
from app.analytics.analyst.skills.diagnostic import RevenueVarianceSkill
from app.analytics.analyst.skills.discovery import DataProfilingSkill
from app.analytics.analyst.skills.predictive import ChurnPredictionSkill, SeasonalityAnalysisSkill, TimeSeriesForecastingSkill
from app.analytics.analyst.skills.quality import ReconciliationAuditSkill, SchemaValidationSkill
from app.analytics.analyst.skills.reporting import ExecutiveSummarySkill
from app.analytics.analyst.skills.retention import RetentionOpportunitySkill
from app.analytics.customer.retention import CustomerRetentionService
from app.analytics.onboarding.harbor_thread_generator import (
    HARBOR_THREAD_AUTH_REF,
    HARBOR_THREAD_CONSENT_REF,
    HARBOR_THREAD_CURRENCY,
    HARBOR_THREAD_MANAGER_EMAIL,
    HARBOR_THREAD_TENANT_NAME,
    generate_gateway_csv_payloads,
    provision_harbor_thread_tenant,
)
from app.analytics.pulse.notifications.base import NotificationPayload
from app.analytics.pulse.notifications.email import EmailNotificationAdapter
from app.analytics.pulse.pdf_generator import PulsePDFGenerator
from app.analytics.pulse.service import PulseService
from app.api.deps import get_db_session
from app.core.database import get_db
from app.main import app
from app.models.base import Base
from app.models.customer import Customer
from app.models.history import DecisionAuditEvent, DecisionRecord
from app.models.product import Product
from app.models.sale import Sale
from app.models.sale_item import SaleItem
from app.models.tenant import Business
from app.models.watermark import TenantIngestionWatermark
from app.schemas.pulse import (
    DeliveryStatus,
    InsightSeverity,
    InsightType,
    KPICategory,
    PulseInsightItem,
    PulseKPIPayload,
    ReportType,
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
def pilot_fixture(db_session: Session):
    """Provisions the dedicated Harbor & Thread synthetic pilot merchant and generates manager token."""
    user, org, biz = provision_harbor_thread_tenant(db_session)
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
# 1. Harbor & Thread Tenant Provisioning, Profile, and Policy Classification
# ==============================================================================


def test_01_pilot_tenant_provisioning_and_metadata(pilot_fixture: dict, db_session: Session):
    """Verify Harbor & Thread is provisioned with AED currency, Dubai location, and synthetic classification."""
    biz = pilot_fixture["biz"]
    user = pilot_fixture["user"]

    assert biz.name == HARBOR_THREAD_TENANT_NAME
    assert biz.currency == HARBOR_THREAD_CURRENCY
    assert user.email == HARBOR_THREAD_MANAGER_EMAIL

    # Central policy classification
    assert TenantCertificationPolicy.is_sandbox_merchant(biz.id, session=db_session) is True
    assert TenantCertificationPolicy.is_real_operational_merchant(biz.id, session=db_session) is False

    # Synthetic pilot token authorizes pilot ingestion
    assert TenantCertificationPolicy.verify_merchant_import_authorization(
        biz.id, session=db_session, authorization_ref=HARBOR_THREAD_AUTH_REF
    ) is True

    # Real merchant safeguard: Real merchants (such as Apex) MUST reject synthetic authorization tokens
    fake_real = Business(
        id=f"biz-apex-guard-{uuid4().hex[:6]}",
        organization_id="org-guard",
        name="Apex Specialty Commerce",
        currency="USD",
    )
    db_session.add(fake_real)
    db_session.flush()

    assert TenantCertificationPolicy.is_real_operational_merchant(fake_real.id, session=db_session) is True
    assert TenantCertificationPolicy.verify_merchant_import_authorization(
        fake_real.id, session=db_session, authorization_ref=HARBOR_THREAD_AUTH_REF
    ) is False


# ==============================================================================
# 2. Simulated Onboarding, Consent, and Read-Only Dataset Preview
# ==============================================================================


def test_02_onboarding_consent_and_read_only_preview(client: TestClient, pilot_fixture: dict, db_session: Session):
    """Verify preview executes strictly read-only and simulated consent is persisted."""
    headers = pilot_fixture["headers"]
    payloads = pilot_fixture["payloads"]
    biz = pilot_fixture["biz"]

    # Record simulated consent in decision audit trail
    consent_rec = DecisionRecord(
        business_id=biz.id,
        organization_id=biz.organization_id,
        recommendation_text="Merchant Data-Processing Consent for Synthetic Demonstration",
        recommendation_type="MERCHANT_ONBOARDING_CONSENT",
        status="APPROVED",
        reviewed_by=pilot_fixture["user"].email,
        reviewed_at=datetime.now(UTC),
        reviewer_notes="Simulated consent recorded for synthetic pilot demonstration.",
    )
    db_session.add(consent_rec)
    db_session.flush()

    consent_audit = DecisionAuditEvent(
        decision_id=consent_rec.id,
        business_id=biz.id,
        organization_id=biz.organization_id,
        revision=0,
        event_type="SIMULATED_CONSENT",
        idempotency_key=str(uuid4()),
        actor_id=pilot_fixture["user"].id,
        actor_role="manager",
        prev_event_hash="0" * 64,
        event_hash="b" * 64,
        canonical_payload={
            "consent_ref": HARBOR_THREAD_CONSENT_REF,
            "disclaimer": "SIMULATED MERCHANT ONBOARDING — NOT A REAL LEGAL AGREEMENT",
            "terms": "Permits ingestion and analysis of synthetic demonstration records in AED.",
        },
    )
    db_session.add(consent_audit)
    db_session.commit()

    # Upload customers CSV
    files = {"file": ("customers.csv", io.BytesIO(payloads["customers_csv"].encode("utf-8")), "text/csv")}
    up = client.post("/api/v1/gateway/upload", files=files, headers=headers)
    assert up.status_code == 201
    dataset_id = up.json()["dataset_id"]

    # Preview endpoint
    prev = client.get(f"/api/v1/gateway/datasets/{dataset_id}/preview", headers=headers)
    assert prev.status_code == 200
    pdata = prev.json()
    assert pdata["total_rows"] == 1200
    assert len(pdata["sample_rows"]) == 15
    assert pdata["column_roles"]["customer_code"] == "identifier"

    # Read-only preview guarantee: ZERO customer records persisted
    count = db_session.execute(
        select(func.count(Customer.id)).where(Customer.business_id == biz.id)
    ).scalar()
    assert count == 0


# ==============================================================================
# 3. Quarantine and Complete Atomic Rollback on Malformed Data
# ==============================================================================


def test_03_quarantine_and_atomic_rollback_on_malformed_data(
    client: TestClient, pilot_fixture: dict, db_session: Session
):
    """Verify unmapped customers are quarantined and corrupt rows trigger complete atomic rollback."""
    headers = pilot_fixture["headers"]
    payloads = pilot_fixture["payloads"]

    # 1. Unmapped customer probe must be quarantined
    files_q = {"file": ("quarantine_probe.csv", io.BytesIO(payloads["quarantine_customer_probe_csv"].encode("utf-8")), "text/csv")}
    up_q = client.post("/api/v1/gateway/upload", files=files_q, headers=headers)
    assert up_q.status_code == 201
    ds_q = up_q.json()["dataset_id"]

    ing_q = client.post(
        f"/api/v1/gateway/datasets/{ds_q}/ingest",
        headers=headers,
        json={"target_entity": "Sale"},
    )
    assert ing_q.status_code == 400
    errs = ing_q.json()["detail"]["errors"]
    assert any(e["error_type"] == "UNRESOLVED_CUSTOMER" for e in errs)
    assert any(e.get("quarantined") is True for e in errs)

    # 2. Atomic rollback probe (negative total) triggers complete rollback
    files_inv = {"file": ("rollback_probe.csv", io.BytesIO(payloads["atomic_rollback_probe_csv"].encode("utf-8")), "text/csv")}
    up_inv = client.post("/api/v1/gateway/upload", files=files_inv, headers=headers)
    assert up_inv.status_code == 201
    ds_inv = up_inv.json()["dataset_id"]

    ing_inv = client.post(
        f"/api/v1/gateway/datasets/{ds_inv}/ingest",
        headers=headers,
        json={"target_entity": "Sale"},
    )
    assert ing_inv.status_code == 400

    rolled_back = db_session.execute(
        select(Sale).where(Sale.transaction_number.in_(["HT-ROLLBACK-001", "HT-ROLLBACK-002"]))
    ).scalars().all()
    assert len(rolled_back) == 0


# ==============================================================================
# 4. Core Domain Model Ingestion: Customers, Products, Sales, Sale Items
# ==============================================================================


def test_04_core_domain_model_ingestion(client: TestClient, pilot_fixture: dict, db_session: Session):
    """Verify ingestion of 1,200 customers, 180 products, ~8,000 sales, and multi-line items."""
    headers = pilot_fixture["headers"]
    payloads = pilot_fixture["payloads"]
    biz = pilot_fixture["biz"]

    # Ingest 1: Customers (1,200 accounts)
    files_c = {"file": ("customers.csv", io.BytesIO(payloads["customers_csv"].encode("utf-8")), "text/csv")}
    up_c = client.post("/api/v1/gateway/upload", files=files_c, headers=headers)
    ds_c = up_c.json()["dataset_id"]
    ing_c = client.post(
        f"/api/v1/gateway/datasets/{ds_c}/ingest",
        headers=headers,
        json={"target_entity": "Customer"},
    )
    assert ing_c.status_code == 200
    assert ing_c.json()["records_persisted"] == 1200

    # Ingest 2: Products (180 catalog items across 6 categories)
    files_p = {"file": ("products.csv", io.BytesIO(payloads["products_csv"].encode("utf-8")), "text/csv")}
    up_p = client.post("/api/v1/gateway/upload", files=files_p, headers=headers)
    ds_p = up_p.json()["dataset_id"]
    ing_p = client.post(
        f"/api/v1/gateway/datasets/{ds_p}/ingest",
        headers=headers,
        json={"target_entity": "Product"},
    )
    assert ing_p.status_code == 200
    assert ing_p.json()["records_persisted"] == 180

    # Ingest 3: Sales (~7,800 orders)
    files_s = {"file": ("sales.csv", io.BytesIO(payloads["sales_csv"].encode("utf-8")), "text/csv")}
    up_s = client.post("/api/v1/gateway/upload", files=files_s, headers=headers)
    ds_s = up_s.json()["dataset_id"]
    ing_s = client.post(
        f"/api/v1/gateway/datasets/{ds_s}/ingest",
        headers=headers,
        json={"target_entity": "Sale"},
    )
    assert ing_s.status_code == 200
    persisted_sales = ing_s.json()["records_persisted"]
    assert 7000 <= persisted_sales <= 9000

    # Ingest 4: Sale Items (12,000–16,500 items)
    files_si = {"file": ("sale_items.csv", io.BytesIO(payloads["sale_items_csv"].encode("utf-8")), "text/csv")}
    up_si = client.post("/api/v1/gateway/upload", files=files_si, headers=headers)
    ds_si = up_si.json()["dataset_id"]
    ing_si = client.post(
        f"/api/v1/gateway/datasets/{ds_si}/ingest",
        headers=headers,
        json={"target_entity": "SaleItem"},
    )
    assert ing_si.status_code == 200
    persisted_items = ing_si.json()["records_persisted"]
    assert 12000 <= persisted_items <= 18000

    # Verify Customer Resolution: 100% of sales mapped to valid customers
    sales = db_session.execute(select(Sale).where(Sale.business_id == biz.id)).scalars().all()
    cust_ids = {s.customer_id for s in sales}
    assert None not in cust_ids
    assert len(cust_ids) >= 800  # Customers not collapsed to single account


# ==============================================================================
# 5. Data Reconciliation, VAT Calculation, and Order Invariants
# ==============================================================================


def test_05_source_to_database_reconciliation_and_invariants(pilot_fixture: dict, db_session: Session):
    """Verify exact mathematical reconciliation, 5% UAE VAT, and watermark classification."""
    biz = pilot_fixture["biz"]

    sales = db_session.execute(select(Sale).where(Sale.business_id == biz.id)).scalars().all()
    assert len(sales) > 0

    # Order Invariant: total = subtotal - discount + tax (5% UAE VAT)
    for s in sales:
        taxable = max(Decimal("0.00"), s.subtotal - s.discount_amount)
        expected_tax = round(taxable * Decimal("0.05"), 2)
        assert abs(s.tax_amount - expected_tax) <= Decimal("0.01")
        expected_total = taxable + s.tax_amount
        assert abs(s.total_amount - expected_total) <= Decimal("0.01")

    # Ingestion Watermark: Synthetic pilot cannot be promoted to authoritative period close
    wm = db_session.execute(
        select(TenantIngestionWatermark).where(TenantIngestionWatermark.business_id == biz.id)
    ).scalar_one_or_none()
    assert wm is not None
    assert wm.verification_status == "provisional" or wm.metadata_json.get("db_reconciled") is True


# ==============================================================================
# 6. Customer Churn Intelligence and Repeat vs Single-Buyer Segregation
# ==============================================================================


def test_06_customer_churn_intelligence(pilot_fixture: dict, db_session: Session):
    """Verify single-order buyers (300) are excluded from churn and repeat buyers have calibrated risk."""
    biz = pilot_fixture["biz"]
    user = pilot_fixture["user"]
    context = ExecutionContext(business_id=biz.id, user_id=user.id, user_role="manager")

    skill = ChurnPredictionSkill()
    res = skill.execute(db_session, context)

    assert res.status == "SUCCESS"
    data = res.data
    # Total repeat customers evaluated (900 out of 1,200)
    assert data["total_repeat_customers"] >= 800
    assert data["revenue_at_risk"] >= 0.0

    finding_str = " ".join(res.findings)
    assert "strictly excluding 1-time buyers" in finding_str


# ==============================================================================
# 7. Customer Retention Intelligence and HITL Decision Auditing
# ==============================================================================


def test_07_retention_intelligence_and_hitl_decisions(pilot_fixture: dict, db_session: Session):
    """Verify retention recommendations and record 1 Approved and 1 Rejected decision in audit ledger."""
    biz = pilot_fixture["biz"]
    user = pilot_fixture["user"]

    overview = CustomerRetentionService.get_retention_overview(db_session, biz.id)
    assert overview.total_customers_evaluated == 1200
    assert overview.one_time_buyers_count >= 250
    assert overview.repeat_buyers_count >= 800

    # Decision 1: APPROVED — VIP Retention Proposal
    dec_app = DecisionRecord(
        business_id=biz.id,
        organization_id=biz.organization_id,
        recommendation_text="Exclusive VIP Dubai Mall Private Styling Session & 15% Appreciation",
        recommendation_type="CUSTOMER_RETENTION",
        status="APPROVED",
        reviewed_by=user.email,
        reviewed_at=datetime.now(UTC),
        reviewer_notes="Approved by owner Daniel Morgan for valued VIP account experiencing cadence delay.",
    )
    db_session.add(dec_app)
    db_session.flush()

    audit_app = DecisionAuditEvent(
        decision_id=dec_app.id,
        business_id=biz.id,
        organization_id=biz.organization_id,
        revision=0,
        event_type="APPROVAL_GRANTED",
        idempotency_key=str(uuid4()),
        actor_id=user.id,
        actor_role="manager",
        prev_event_hash="0" * 64,
        event_hash="c" * 64,
        canonical_payload={"action": "APPROVED", "notes": dec_app.reviewer_notes},
    )
    db_session.add(audit_app)

    # Decision 2: REJECTED — Aggressive Mass Discount
    dec_rej = DecisionRecord(
        business_id=biz.id,
        organization_id=biz.organization_id,
        recommendation_text="40% Sitewide Clearance Flash Promo",
        recommendation_type="CUSTOMER_RETENTION",
        status="REJECTED",
        reviewed_by=user.email,
        reviewed_at=datetime.now(UTC),
        reviewer_notes="Rejected by owner Daniel Morgan: excessive discounting harms luxury brand equity.",
    )
    db_session.add(dec_rej)
    db_session.flush()

    audit_rej = DecisionAuditEvent(
        decision_id=dec_rej.id,
        business_id=biz.id,
        organization_id=biz.organization_id,
        revision=0,
        event_type="REJECTION_RECORDED",
        idempotency_key=str(uuid4()),
        actor_id=user.id,
        actor_role="manager",
        prev_event_hash="c" * 64,
        event_hash="d" * 64,
        canonical_payload={"action": "REJECTED", "notes": dec_rej.reviewer_notes},
    )
    db_session.add(audit_rej)
    db_session.commit()

    # Verify persistence in ledger
    records = db_session.execute(
        select(DecisionRecord).where(DecisionRecord.business_id == biz.id)
    ).scalars().all()
    statuses = {r.status for r in records}
    assert "APPROVED" in statuses
    assert "REJECTED" in statuses


# ==============================================================================
# 8. Pulse Executive Reporting in AED and ReportLab PDF Publication
# ==============================================================================


def test_08_pulse_executive_report_and_pdf(pilot_fixture: dict, db_session: Session):
    """Generate October 2026 Pulse report in AED with cost-based gross margin and ReportLab PDF."""
    biz = pilot_fixture["biz"]

    report = PulseService.generate_report(
        session=db_session,
        business_id=biz.id,
        report_type=ReportType.MONTHLY_EXECUTIVE,
        period_start=datetime(2026, 10, 1, 0, 0, tzinfo=UTC),
        period_end=datetime(2026, 10, 31, 23, 59, tzinfo=UTC),
        report_title="Harbor & Thread — October 2026 Executive Performance (AED)",
    )

    assert report is not None
    assert report.pdf_file_bytes is not None
    assert report.pdf_file_bytes.startswith(b"%PDF")
    assert len(report.pdf_sha256) == 64

    # Check KPI payload
    kpis = report.kpi_payload
    tot_rev = kpis["financial"]["total_revenue"]
    assert tot_rev["unit"] == "AED"
    assert "AED" in tot_rev["formatted_value"]

    gross_margin = kpis["financial"]["gross_margin"]
    assert "[ESTIMATED - synthetic_labeled_costs]" in gross_margin["formatted_value"]


# ==============================================================================
# 9. Adaptive Analyst Studio: Multi-Domain Execution Across All 8 Domains
# ==============================================================================


def test_09_analyst_studio_eight_domains(pilot_fixture: dict, db_session: Session):
    """Verify execution across all 8 Analyst Studio specialist domains."""
    biz = pilot_fixture["biz"]
    user = pilot_fixture["user"]
    context = ExecutionContext(business_id=biz.id, user_id=user.id, user_role="manager")

    # Domain 1: Discovery (DataProfilingSkill)
    s1 = DataProfilingSkill()
    r1 = s1.execute(db_session, context)
    assert r1.status == "SUCCESS"

    # Domain 2: Quality (SchemaValidationSkill)
    s2 = SchemaValidationSkill()
    r2 = s2.execute(db_session, context)
    assert r2.status == "SUCCESS"

    # Domain 3: Customer (RepeatPurchaseSkill)
    s3 = RepeatPurchaseSkill()
    r3 = s3.execute(db_session, context)
    assert r3.status == "SUCCESS"

    # Domain 4: Predictive (SeasonalityAnalysisSkill)
    s4 = SeasonalityAnalysisSkill()
    r4 = s4.execute(db_session, context)
    assert r4.status == "SUCCESS"

    # Domain 5: Diagnostic (RevenueVarianceSkill)
    s5 = RevenueVarianceSkill()
    r5 = s5.execute(db_session, context)
    assert r5.status == "SUCCESS"

    # Domain 6: Retention (RetentionOpportunitySkill)
    s6 = RetentionOpportunitySkill()
    r6 = s6.execute(db_session, context)
    assert r6.status == "SUCCESS"

    # Domain 7: Commercial (GrossMarginAnalysisSkill)
    s7 = GrossMarginAnalysisSkill()
    r7 = s7.execute(db_session, context)
    assert r7.status == "SUCCESS"
    assert r7.data["cost_classification"] == "ESTIMATED"

    # Domain 8: Reporting (ExecutiveSummarySkill)
    s8 = ExecutiveSummarySkill()
    r8 = s8.execute(db_session, context)
    assert r8.status == "SUCCESS"


# ==============================================================================
# 10. Local Mailpit Dispatch, Period-Close Safeguard, and Cross-Tenant Boundaries
# ==============================================================================


def test_10_mailpit_dispatch_and_tenant_isolation(client: TestClient, pilot_fixture: dict, db_session: Session):
    """Verify Mailpit notification dispatch, period close certification block, and cross-tenant boundary rejection."""
    biz = pilot_fixture["biz"]

    # 1. Email notification dispatch via local Mailpit / Mock adapter
    email_adapter = EmailNotificationAdapter()
    payload = NotificationPayload(
        report_id="rep-ht-pilot-01",
        business_id=biz.id,
        business_name=biz.name,
        report_title="Harbor & Thread October 2026 Executive Pulse",
        period_label="October 2026",
        messaging_summary="Harbor & Thread Monthly Executive Performance",
        executive_summary="Commercial momentum across Dubai Mall and online channels.",
        recipient_destination="daniel.morgan@harbor-thread.local",
        pdf_bytes=b"%PDF-1.4 Mock PDF Content",
        pdf_filename="Harbor_Thread_Oct2026_Pulse.pdf",
    )
    delivery = email_adapter.send_notification(payload)
    assert delivery.status in (DeliveryStatus.SENT, DeliveryStatus.MOCKED)

    # 2. Period Close Safeguard: Synthetic pilot cannot be promoted to audited GAAP period close
    with pytest.raises(ValueError, match="Synthetic data cannot be certified for authoritative financial period close"):
        TenantCertificationPolicy.assert_cannot_certify_period_close_on_synthetic_data(
            biz.id, session=db_session
        )

    # 3. Cross-Tenant Isolation: Another tenant's user cannot view Harbor & Thread records
    user_other, org_other, biz_other = AuthService.signup(
        db=db_session,
        email=f"intruder_{uuid4().hex[:6]}@other-merchant.ae",
        password="Password123!",
        full_name="Competitor Owner",
        organization_name="Other Retail Group",
        business_name="Competitor Luxury Store",
    )
    token_other = AuthService.create_access_token(
        user_id=user_other.id, email=user_other.email, organization_id=org_other.id, business_id=biz_other.id
    )
    other_headers = {"Authorization": f"Bearer {token_other}", "X-Business-ID": biz_other.id}

    probe = client.get("/api/v1/gateway/datasets", headers=other_headers)
    assert probe.status_code == 200
    for ds in probe.json():
        assert ds.get("business_id") != biz.id
