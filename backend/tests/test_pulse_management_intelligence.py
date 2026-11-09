"""Comprehensive test suite for NEXUS Pulse (Management Intelligence & Automated Reporting).

Validates:
1. KPI Intelligence Framework calculations (Financial, Customer, Churn, Retention, Product, Operational).
2. Insight generation and strict taxonomy categorization (Fact, KPI, Observation, Model, Action).
3. Executive ReportLab PDF generation and SHA-256 cryptographic digest integrity.
4. Scheduling and trigger engine (daily, weekly, monthly frequencies, timezone conversions, idempotency).
5. Provider-neutral notification channels (WhatsApp, Telegram, Email) with recipient validation and mock fallback.
6. Recipient opt-out policy enforcement.
7. Multi-tenant isolation and secure expiring token access.
8. Watermark verification safety gate propagation.
9. End-to-end FastAPI REST endpoints integration.
"""

import hashlib
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from app.analytics.pulse.insights import PulseInsightEngine
from app.analytics.pulse.kpi_catalogue import PulseKPICatalogueEngine
from app.analytics.pulse.notifications.email import EmailNotificationAdapter
from app.analytics.pulse.notifications.telegram import TelegramNotificationAdapter
from app.analytics.pulse.notifications.whatsapp import WhatsAppNotificationAdapter
from app.analytics.pulse.pdf_generator import PulsePDFGenerator
from app.analytics.pulse.scheduler import PulseScheduler
from app.analytics.pulse.service import PulseService
from app.models.base import Base
from app.models.customer import Customer
from app.models.history import DecisionRecord
from app.models.product import Product
from app.models.pulse import (
    PulseDeliveryLog,
    PulseGeneratedReport,
    PulseRecipientPreference,
    PulseReportSchedule,
)
from app.models.sale import Sale
from app.models.sale_item import SaleItem
from app.models.tenant import Business, Organization
from app.schemas.pulse import (
    DeliveryChannel,
    DeliveryStatus,
    InsightSeverity,
    InsightType,
    KPICategory,
    PulseRecipientOptRequest,
    PulseTestDispatchRequest,
    RecipientOptStatus,
    ReportFrequency,
    ReportType,
)
from app.services.watermark_service import WatermarkContract, WatermarkService
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker


@pytest.fixture
def pulse_db_session():
    """Create an isolated in-memory SQLite database session for Pulse tests."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


def _seed_pulse_tenant(
    session: Session,
    business_id: str,
    name: str = "Pulse Retailer",
) -> Business:
    """Helper to seed organization and business tenant."""
    org_id = f"org-{uuid4().hex[:8]}"
    org = Organization(id=org_id, name=f"{name} Org", slug=f"slug-{uuid4().hex[:6]}")
    biz = Business(
        id=business_id,
        name=name,
        organization_id=org_id,
        industry="Omnichannel Retail",
        currency="USD",
    )
    session.add_all([org, biz])
    session.commit()
    return biz


def _seed_commercial_records(session: Session, business_id: str):
    """Seed customers, products, sales, and line items for KPI verification."""
    # 1. Products
    p1 = Product(
        sku="PROD-01",
        name="Artisan Espresso Beans",
        category="Coffee",
        subcategory="Whole Bean",
        selling_price=Decimal("25.00"),
        unit_cost=Decimal("10.00"),
        active=True,
        business_id=business_id,
    )
    p2 = Product(
        sku="PROD-02",
        name="Ceramic Dripper",
        category="Brewing Gear",
        subcategory="Drippers",
        selling_price=Decimal("40.00"),
        unit_cost=Decimal("15.00"),
        active=True,
        business_id=business_id,
    )
    session.add_all([p1, p2])
    session.flush()

    # 2. Customers
    c1 = Customer(
        customer_code="CUST-01",
        name="Alice Buyer",
        email="alice@test.com",
        city="San Francisco",
        customer_segment="Retail",
        acquisition_date=date(2023, 1, 1),
        business_id=business_id,
    )
    c2 = Customer(
        customer_code="CUST-02",
        name="Bob Regular",
        email="bob@test.com",
        city="Oakland",
        customer_segment="Retail",
        acquisition_date=date(2023, 1, 15),
        business_id=business_id,
    )
    session.add_all([c1, c2])
    session.flush()

    # 3. Completed Sales in current window (May 2023)
    s1 = Sale(
        transaction_number="TXN-001",
        customer_id=c1.id,
        transaction_date=datetime(2023, 5, 5, 10, 0, tzinfo=UTC),
        subtotal=Decimal("50.00"),
        total_amount=Decimal("50.00"),
        status="completed",
        business_id=business_id,
    )
    s2 = Sale(
        transaction_number="TXN-002",
        customer_id=c1.id,
        transaction_date=datetime(2023, 5, 15, 11, 0, tzinfo=UTC),
        subtotal=Decimal("80.00"),
        total_amount=Decimal("80.00"),
        status="completed",
        business_id=business_id,
    )
    s3 = Sale(
        transaction_number="TXN-003",
        customer_id=c2.id,
        transaction_date=datetime(2023, 5, 20, 14, 0, tzinfo=UTC),
        subtotal=Decimal("40.00"),
        total_amount=Decimal("40.00"),
        status="completed",
        business_id=business_id,
    )
    session.add_all([s1, s2, s3])
    session.flush()

    # 4. Sale Items (attached via foreign keys without business_id column)
    session.add_all([
        SaleItem(sale_id=s1.id, product_id=p1.id, quantity=2, unit_price=Decimal("25.00"), line_total=Decimal("50.00")),
        SaleItem(sale_id=s2.id, product_id=p2.id, quantity=2, unit_price=Decimal("40.00"), line_total=Decimal("80.00")),
        SaleItem(sale_id=s3.id, product_id=p2.id, quantity=1, unit_price=Decimal("40.00"), line_total=Decimal("40.00")),
    ])

    # 5. Prior Period Sales (April 2023 for comparative calculations)
    s_prior = Sale(
        transaction_number="TXN-PRIOR-01",
        customer_id=c1.id,
        transaction_date=datetime(2023, 4, 10, 10, 0, tzinfo=UTC),
        subtotal=Decimal("100.00"),
        total_amount=Decimal("100.00"),
        status="completed",
        business_id=business_id,
    )
    session.add(s_prior)

    # 6. Seed a pending retention proposal to trigger prescriptive recommended action insight
    dec = DecisionRecord(
        business_id=business_id,
        recommendation_type="CUSTOMER_RETENTION",
        status="PENDING",
        recommendation_text="Recommend phone outreach for at-risk buyer",
    )
    session.add(dec)
    session.commit()


# ==============================================================================
# 1. KPI INTELLIGENCE FRAMEWORK & ACCURACY TESTS
# ==============================================================================

def test_kpi_catalogue_computations_and_integrity(pulse_db_session: Session):
    """
    Test deterministic calculation of financial, customer, product, and operational KPIs.
    Verifies no invented values or silent zero replacements occur.
    """
    session = pulse_db_session
    biz_id = "biz-pulse-kpi-1"
    _seed_pulse_tenant(session, biz_id, "Specialty Roasters")
    _seed_commercial_records(session, biz_id)

    # Certify watermark through end of May 2023
    cutoff = datetime(2023, 5, 31, 23, 59, 59, tzinfo=UTC)
    WatermarkService.record_watermark(
        session,
        WatermarkContract(
            business_id=biz_id,
            source_id="default",
            complete_through_dt=cutoff,
            provenance_type="accounting_period_close",
            verification_status="verified",
        ),
    )
    session.commit()

    p_start = datetime(2023, 5, 1, 0, 0, tzinfo=UTC)
    p_end = datetime(2023, 5, 31, 23, 59, 59, tzinfo=UTC)
    c_start = datetime(2023, 4, 1, 0, 0, tzinfo=UTC)
    c_end = datetime(2023, 4, 30, 23, 59, 59, tzinfo=UTC)

    payload = PulseKPICatalogueEngine.compute_all_kpis(
        session=session,
        business_id=biz_id,
        period_start=p_start,
        period_end=p_end,
        comparison_period_start=c_start,
        comparison_period_end=c_end,
    )

    # 1. Financial Verification
    # Current orders: $50 + $80 + $40 = $170.00, count = 3 orders
    fin = payload.financial
    assert fin["total_revenue"].value == 170.0
    assert fin["total_revenue"].formatted_value == "$170.00"
    assert fin["total_orders"].value == 3
    # AOV: 170 / 3 = 56.67
    assert fin["average_order_value"].value == pytest.approx(56.67, 0.01)

    # Prior revenue: $100.00. Growth = ((170 - 100) / 100) * 100 = +70.0%
    assert fin["revenue_growth"].value == pytest.approx(70.0, 0.1)

    # Margin: Revenue = $170. Cost = (2*10) + (2*15) + (1*15) = 20 + 30 + 15 = $65. Profit = 105. Margin = 105/170 = 61.8%
    assert fin["gross_margin"].value == pytest.approx(61.8, 0.2)

    # 2. Customer Verification
    cust = payload.customer
    assert cust["active_customers"].value == 2
    # Alice ordered 2 times, Bob ordered 1 time. Repeat buyer count = 1. Repeat rate = 1/2 = 50.0%
    assert cust["repeat_purchase_rate"].value == pytest.approx(50.0, 0.1)

    # 3. Product & Top Items Verification
    assert len(payload.top_products) > 0
    top_p = payload.top_products[0]
    # Ceramic Dripper revenue = $80 + $40 = $120.00, units = 3
    assert top_p["name"] == "Ceramic Dripper"
    assert top_p["revenue"] == 120.0
    assert top_p["units_sold"] == 3

    # 4. Operational & Watermark Verification
    ops = payload.operational
    assert ops["watermark_verification_status"].value == "verified_complete"
    assert ops["certified_complete_through"].value == cutoff.isoformat()


# ==============================================================================
# 2. INSIGHT GENERATION & TAXONOMY CLASSIFICATION TESTS
# ==============================================================================

def test_insight_engine_categorization_and_narrative(pulse_db_session: Session):
    """
    Test insight generation according to the 5 strict types:
    - Observed Fact
    - Calculated KPI
    - Statistical Observation
    - Model Interpretation
    - Recommended Action
    """
    session = pulse_db_session
    biz_id = "biz-pulse-insights-1"
    _seed_pulse_tenant(session, biz_id, "Artisan Roasters")
    _seed_commercial_records(session, biz_id)

    p_start = datetime(2023, 5, 1, 0, 0, tzinfo=UTC)
    p_end = datetime(2023, 5, 31, 23, 59, 59, tzinfo=UTC)
    c_start = datetime(2023, 4, 1, 0, 0, tzinfo=UTC)
    c_end = datetime(2023, 4, 30, 23, 59, 59, tzinfo=UTC)
    payload = PulseKPICatalogueEngine.compute_all_kpis(
        session=session,
        business_id=biz_id,
        period_start=p_start,
        period_end=p_end,
        comparison_period_start=c_start,
        comparison_period_end=c_end,
    )

    insights, narrative, msg_text = PulseInsightEngine.generate_insights_and_summaries(
        kpi_payload=payload,
        business_name="Artisan Roasters",
        period_label="May 2023",
        report_url="https://app.nexus.internal/pulse/report/test123",
    )

    assert len(insights) >= 4

    types_found = {i.type for i in insights}
    assert InsightType.OBSERVED_FACT in types_found
    assert InsightType.CALCULATED_KPI in types_found
    assert InsightType.RECOMMENDED_ACTION in types_found

    # Verify Executive Narrative Prose
    assert "Executive Intelligence Overview" in narrative
    assert "Artisan Roasters" in narrative
    assert "May 2023" in narrative
    assert "$170.00" in narrative

    # Verify WhatsApp / Telegram Markdown Format
    assert "NEXUS Pulse — Executive Update" in msg_text
    assert "*Revenue:*" in msg_text
    assert "$170.00" in msg_text
    assert "https://app.nexus.internal/pulse/report/test123" in msg_text


# ==============================================================================
# 3. PDF GENERATION & CRYPTOGRAPHIC INTEGRITY TESTS
# ==============================================================================

def test_pulse_pdf_generator_integrity(pulse_db_session: Session):
    """
    Test high-fidelity ReportLab PDF generation, table formatting, and SHA-256 digest binding.
    """
    session = pulse_db_session
    biz_id = "biz-pulse-pdf-1"
    _seed_pulse_tenant(session, biz_id, "Apex Luxury Goods")
    _seed_commercial_records(session, biz_id)

    p_start = datetime(2023, 5, 1, 0, 0, tzinfo=UTC)
    p_end = datetime(2023, 5, 31, 23, 59, 59, tzinfo=UTC)
    c_start = datetime(2023, 4, 1, 0, 0, tzinfo=UTC)
    c_end = datetime(2023, 4, 30, 23, 59, 59, tzinfo=UTC)
    payload = PulseKPICatalogueEngine.compute_all_kpis(
        session=session,
        business_id=biz_id,
        period_start=p_start,
        period_end=p_end,
        comparison_period_start=c_start,
        comparison_period_end=c_end,
    )
    insights, narrative, _ = PulseInsightEngine.generate_insights_and_summaries(
        kpi_payload=payload,
        business_name="Apex Luxury Goods",
        period_label="May 2023",
    )

    pdf_bytes, sha_digest = PulsePDFGenerator.generate_pdf_report(
        report_id="rep-pdf-test-1",
        business_name="Apex Luxury Goods",
        period_label="May 2023",
        kpi_payload=payload,
        insights=insights,
        executive_summary=narrative,
        watermark_status="verified_complete",
    )

    # 1. Valid PDF header
    assert pdf_bytes.startswith(b"%PDF")
    assert len(pdf_bytes) > 2000

    # 2. SHA-256 Digest matches exact bytes
    calculated_digest = hashlib.sha256(pdf_bytes).hexdigest()
    assert sha_digest == calculated_digest


# ==============================================================================
# 4. SCHEDULER & TRIGGER ENGINE TESTS
# ==============================================================================

def test_scheduler_calculations_and_execution(pulse_db_session: Session):
    """
    Test scheduling engine: calculate_next_run with timezones and process_due_schedules execution.
    """
    session = pulse_db_session
    biz_id = "biz-pulse-sched-1"
    biz = _seed_pulse_tenant(session, biz_id, "Schedule Test Merchant")

    scheduler = PulseScheduler()

    # 1. Next run calculation - Daily at 08:00 UTC
    ref_dt = datetime(2023, 6, 1, 7, 0, tzinfo=UTC)
    next_daily = scheduler.calculate_next_run(
        frequency=ReportFrequency.DAILY,
        time_of_day="08:00",
        timezone_str="UTC",
        from_dt=ref_dt,
    )
    assert next_daily == datetime(2023, 6, 1, 8, 0, tzinfo=UTC)

    # 2. Next run calculation - Monthly on 1st at 09:00 UTC
    next_monthly = scheduler.calculate_next_run(
        frequency=ReportFrequency.MONTHLY,
        time_of_day="09:00",
        timezone_str="UTC",
        day_of_month=1,
        from_dt=ref_dt,
    )
    # Since June 1 07:00 is before 09:00, next run is today June 1 09:00
    assert next_monthly == datetime(2023, 6, 1, 9, 0, tzinfo=UTC)

    # 3. Create a due schedule in DB
    sched = PulseReportSchedule(
        business_id=biz_id,
        organization_id=biz.organization_id,
        schedule_name="Executive Morning Brief",
        report_type=ReportType.MONTHLY_EXECUTIVE.value,
        frequency=ReportFrequency.DAILY.value,
        time_of_day="08:00",
        timezone="UTC",
        channel_types=[DeliveryChannel.EMAIL.value, DeliveryChannel.TELEGRAM.value],
        recipients_json=[
            {"channel": "EMAIL", "destination": "cfo@company.com", "name": "CFO"},
            {"channel": "TELEGRAM", "destination": "123456789", "name": "Telegram Ops"},
        ],
        kpi_categories=["financial", "customer", "churn"],
        is_enabled=True,
        next_run_at=datetime(2023, 6, 1, 7, 59, tzinfo=UTC),  # due
    )
    session.add(sched)
    session.commit()

    # Run due schedules
    gen_ids = scheduler.process_due_schedules(session, as_of_time=datetime(2023, 6, 1, 8, 5, tzinfo=UTC))
    assert len(gen_ids) == 1

    # Verify report was generated and scheduled forward
    report = session.get(PulseGeneratedReport, gen_ids[0])
    assert report is not None
    assert report.business_id == biz_id
    assert report.pdf_file_bytes is not None

    session.refresh(sched)
    assert sched.last_run_at is not None
    next_run = sched.next_run_at.replace(tzinfo=UTC) if sched.next_run_at.tzinfo is None else sched.next_run_at
    assert next_run > datetime(2023, 6, 1, 8, 5, tzinfo=UTC)

    # Verify delivery logs recorded
    logs = session.execute(
        select(PulseDeliveryLog).where(PulseDeliveryLog.report_id == report.id)
    ).scalars().all()
    assert len(logs) == 2


# ==============================================================================
# 5. NOTIFICATION ADAPTERS & RECIPIENT PREFERENCES
# ==============================================================================

def test_notification_channel_validation_and_opt_out(pulse_db_session: Session):
    """
    Test WhatsApp, Telegram, and Email adapter input validations and opt-out policy enforcement.
    """
    session = pulse_db_session
    biz_id = "biz-pulse-adapters-1"
    biz = _seed_pulse_tenant(session, biz_id, "Messaging Test Merchant")

    # 1. WhatsApp Validation
    wa = WhatsAppNotificationAdapter()
    assert wa.validate_phone("+1 (415) 555-2671") == "+14155552671"
    with pytest.raises(ValueError):
        wa.validate_phone("invalid-phone-string")
    with pytest.raises(ValueError):
        wa.validate_phone("   ")

    # 2. Telegram Validation
    tg = TelegramNotificationAdapter()
    assert tg.validate_chat_id("987654321") == "987654321"
    with pytest.raises(ValueError):
        tg.validate_chat_id("   ")

    # 3. Email Validation
    em = EmailNotificationAdapter()
    assert em.validate_email("director@enterprise.com") == "director@enterprise.com"
    with pytest.raises(ValueError):
        em.validate_email("invalid-email-address")

    # 4. Opt-Out Policy Enforcement
    # Register opted-out recipient in DB
    pref = PulseRecipientPreference(
        business_id=biz_id,
        organization_id=biz.organization_id,
        recipient_name="Opted Out Officer",
        channel=DeliveryChannel.WHATSAPP.value,
        destination="+14155552671",
        opt_status=RecipientOptStatus.OPTED_OUT.value,
    )
    session.add(pref)
    session.commit()

    # Generate a report for test dispatch
    rep = PulseService.generate_report(
        session=session,
        business_id=biz_id,
        report_type=ReportType.WEEKLY_MANAGEMENT,
        period_start=datetime(2023, 5, 1, tzinfo=UTC),
        period_end=datetime(2023, 5, 7, tzinfo=UTC),
    )

    test_req = PulseTestDispatchRequest(
        report_id=rep.id,
        channel=DeliveryChannel.WHATSAPP,
        destination="+14155552671",
        recipient_name="Opted Out Officer",
    )
    log_item = PulseService.dispatch_test_report(session, biz_id, test_req)
    assert log_item.status == DeliveryStatus.FAILED
    assert "opted out" in (log_item.error_message or "").lower()


# ==============================================================================
# 6. MULTI-TENANT ISOLATION & EXPIRING REPORT ACCESS
# ==============================================================================

def test_multi_tenant_isolation_and_token_expiry(pulse_db_session: Session):
    """
    Test strict multi-tenant isolation and secure 30-day expiring public token access.
    """
    session = pulse_db_session
    biz_a = "biz-pulse-alpha"
    biz_b = "biz-pulse-beta"
    _seed_pulse_tenant(session, biz_a, "Tenant Alpha")
    _seed_pulse_tenant(session, biz_b, "Tenant Beta")

    # Generate report for Tenant Alpha
    rep_a = PulseService.generate_report(
        session=session,
        business_id=biz_a,
        report_type=ReportType.MONTHLY_EXECUTIVE,
        period_start=datetime(2023, 5, 1, tzinfo=UTC),
        period_end=datetime(2023, 5, 31, tzinfo=UTC),
    )

    # Tenant Alpha can access their own report and download PDF
    own_rep = PulseService.get_report(session, rep_a.id, business_id=biz_a)
    assert own_rep.id == rep_a.id
    pdf_bytes, filename = PulseService.get_report_pdf(session, rep_a.id, business_id=biz_a)
    assert pdf_bytes is not None and len(pdf_bytes) > 0
    assert pdf_bytes.startswith(b"%PDF")
    assert filename.endswith(".pdf")

    # Tenant Beta CANNOT access Tenant Alpha's report (IDOR Protection -> PermissionError)
    with pytest.raises((PermissionError, ValueError), match="Access denied"):
        PulseService.get_report(session, rep_a.id, business_id=biz_b)

    with pytest.raises((PermissionError, ValueError), match="Access denied"):
        PulseService.get_report_pdf(session, rep_a.id, business_id=biz_b)

    # Missing report raises FileNotFoundError
    with pytest.raises(FileNotFoundError, match="does not exist"):
        PulseService.get_report(session, "nonexistent-report-id", business_id=biz_a)

    with pytest.raises(FileNotFoundError, match="does not exist"):
        PulseService.get_report_pdf(session, "nonexistent-report-id", business_id=biz_a)

    # Report with missing PDF artifact raises FileNotFoundError
    rep_no_pdf = PulseGeneratedReport(
        id="rep-missing-pdf",
        business_id=biz_a,
        organization_id="org_test",
        report_title="No PDF Report",
        report_type="MONTHLY_EXECUTIVE",
        period_start=datetime(2023, 5, 1, tzinfo=UTC),
        period_end=datetime(2023, 5, 31, tzinfo=UTC),
        kpi_payload={},
        insights_json=[],
        executive_summary="Summary",
        messaging_summary="Msg",
        pdf_file_bytes=None,  # Missing PDF artifact
        watermark_status="verified_complete",
        access_token="token-no-pdf",
        token_expires_at=datetime.now(UTC) + timedelta(days=30),
    )
    session.add(rep_no_pdf)
    session.commit()

    with pytest.raises(FileNotFoundError, match="missing or not generated"):
        PulseService.get_report_pdf(session, "rep-missing-pdf", business_id=biz_a)

    # Expiring Public Token Access:
    # Valid token within expiration window works
    token_rep = PulseService.get_public_report(session, rep_a.access_token)
    assert token_rep.id == rep_a.id
    assert token_rep.report_title == rep_a.report_title

    # Expired token raises error
    db_rep = session.get(PulseGeneratedReport, rep_a.id)
    db_rep.token_expires_at = datetime.now(UTC) - timedelta(hours=1)  # expired
    session.commit()

    with pytest.raises(ValueError, match="expired"):
        PulseService.get_public_report(session, rep_a.access_token)

    with pytest.raises(ValueError, match="expired"):
        PulseService.get_report_pdf(session, rep_a.id, access_token=rep_a.access_token)


# ==============================================================================
# 7. WATERMARK SAFETY GATE ENFORCEMENT
# ==============================================================================

def test_unverified_watermark_warning_in_pulse_report(pulse_db_session: Session):
    """
    Verify that unverified or missing watermark boundaries trigger diagnostic alerts
    and restriction notices in Pulse intelligence reports.
    """
    session = pulse_db_session
    biz_id = "biz-pulse-unverified"
    _seed_pulse_tenant(session, biz_id, "Apex Specialty Commerce")  # diagnostic only tenant

    p_start = datetime(2023, 5, 1, 0, 0, tzinfo=UTC)
    p_end = datetime(2023, 5, 31, 23, 59, 59, tzinfo=UTC)
    c_start = datetime(2023, 4, 1, 0, 0, tzinfo=UTC)
    c_end = datetime(2023, 4, 30, 23, 59, 59, tzinfo=UTC)

    payload = PulseKPICatalogueEngine.compute_all_kpis(
        session=session,
        business_id=biz_id,
        period_start=p_start,
        period_end=p_end,
        comparison_period_start=c_start,
        comparison_period_end=c_end,
    )
    insights, narrative, _ = PulseInsightEngine.generate_insights_and_summaries(
        kpi_payload=payload,
        business_name="Apex Specialty Commerce",
        period_label="May 2023",
    )
    assert "Source completeness is UNVERIFIED" in narrative
    assert "Data completeness is certified" not in narrative

    ops_kpi = payload.operational["watermark_verification_status"]
    assert "DIAGNOSTIC_ONLY" in ops_kpi.limitations or "provisional" in ops_kpi.limitations

    # Check for Critical Completeness Notice in Insights
    wm_insights = [i for i in insights if i.category == KPICategory.OPERATIONAL]
    assert len(wm_insights) >= 1
    assert wm_insights[0].severity == InsightSeverity.CRITICAL
    assert "Data Completeness Notice" in wm_insights[0].title


# ==============================================================================
# 8. FASTAPI REST ENDPOINTS INTEGRATION
# ==============================================================================

def test_fastapi_pulse_endpoints(api_client: TestClient, auth_headers: dict[str, str]):
    """
    Test FastAPI endpoints under /api/v1/pulse/*.
    """
    client = api_client
    headers = auth_headers

    # 1. GET /dashboard (returns PulseDashboardOverview schema directly)
    res_dash = client.get("/api/v1/pulse/dashboard", headers=headers)
    assert res_dash.status_code == 200
    dash_json = res_dash.json()
    assert "kpi_payload" in dash_json
    assert "insights" in dash_json
    assert "revenue_trend" in dash_json["kpi_payload"]
    assert "risk_distribution" in dash_json["kpi_payload"]

    # 2. POST /reports/generate (with idempotency testing)
    idem_key = f"test-key-{uuid4().hex[:8]}"
    gen_payload = {
        "report_type": "MONTHLY_EXECUTIVE",
        "date_from": "2023-05-01T00:00:00Z",
        "date_to": "2023-05-31T23:59:59Z",
        "idempotency_key": idem_key,
    }
    res_gen = client.post("/api/v1/pulse/reports/generate", json=gen_payload, headers=headers)
    assert res_gen.status_code == 200
    gen_json = res_gen.json()
    assert gen_json["success"] is True
    rep_id = gen_json["data"]["report_id"]
    access_token = gen_json["data"]["access_token"]

    # Repeat generate request with same idempotency_key must return same report_id
    res_gen_repeat = client.post("/api/v1/pulse/reports/generate", json=gen_payload, headers=headers)
    assert res_gen_repeat.status_code == 200
    assert res_gen_repeat.json()["data"]["report_id"] == rep_id

    # 3. GET /reports list
    res_list = client.get("/api/v1/pulse/reports?page=1&page_size=10", headers=headers)
    assert res_list.status_code == 200
    list_json = res_list.json()
    assert list_json["success"] is True
    assert list_json["data"]["total_count"] >= 1

    # 4. GET /reports/{report_id}
    res_det = client.get(f"/api/v1/pulse/reports/{rep_id}", headers=headers)
    assert res_det.status_code == 200
    det_json = res_det.json()
    assert det_json["id"] == rep_id
    assert det_json["pdf_sha256"] is not None

    # 5. GET /reports/{report_id}/pdf
    res_pdf = client.get(f"/api/v1/pulse/reports/{rep_id}/pdf", headers=headers)
    assert res_pdf.status_code == 200
    assert res_pdf.headers["content-type"] == "application/pdf"
    assert res_pdf.content.startswith(b"%PDF")

    # 5a. Missing report ID raises 404
    res_pdf_404 = client.get("/api/v1/pulse/reports/rep-does-not-exist/pdf", headers=headers)
    assert res_pdf_404.status_code == 404

    # 5b. Unauthenticated request raises 401 when business context is provided without valid bearer
    res_pdf_401 = client.get(f"/api/v1/pulse/reports/{rep_id}/pdf", headers={"X-Business-ID": "biz_test_suite"})
    assert res_pdf_401.status_code == 401

    # 5c. Request without any headers raises 400 (tenant context missing)
    res_pdf_no_tenant = client.get(f"/api/v1/pulse/reports/{rep_id}/pdf")
    assert res_pdf_no_tenant.status_code == 400

    # 6. GET /public/reports/{access_token} (No auth required)
    res_pub = client.get(f"/api/v1/pulse/public/reports/{access_token}")
    assert res_pub.status_code == 200
    pub_json = res_pub.json()
    assert pub_json["id"] == rep_id

    # 6a. GET /public/reports/{access_token}/pdf (No auth required)
    res_pub_pdf = client.get(f"/api/v1/pulse/public/reports/{access_token}/pdf")
    assert res_pub_pdf.status_code == 200
    assert res_pub_pdf.headers["content-type"] == "application/pdf"
    assert res_pub_pdf.content.startswith(b"%PDF")

    # 7. POST /schedules
    sched_payload = {
        "schedule_name": "Weekly Monday Ops Digest",
        "report_type": "WEEKLY_MANAGEMENT",
        "frequency": "WEEKLY",
        "day_of_week": 0,
        "time_of_day": "09:00",
        "timezone": "UTC",
        "channel_types": ["EMAIL", "TELEGRAM"],
        "recipients": [
            {"channel": "EMAIL", "destination": "lead@company.com", "name": "Team Lead"},
        ],
        "kpi_categories": ["FINANCIAL", "CUSTOMER"],
    }
    res_sched = client.post("/api/v1/pulse/schedules", json=sched_payload, headers=headers)
    assert res_sched.status_code == 200
    sched_json = res_sched.json()
    sched_id = sched_json["id"]
    assert sched_json["schedule_name"] == "Weekly Monday Ops Digest"

    # 8. PUT /schedules/{schedule_id}
    res_upd = client.put(
        f"/api/v1/pulse/schedules/{sched_id}",
        json={"is_enabled": False, "schedule_name": "Paused Weekly Ops Digest"},
        headers=headers,
    )
    assert res_upd.status_code == 200
    assert res_upd.json()["is_enabled"] is False

    # 9. POST /dispatch/test
    test_dispatch_payload = {
        "report_id": rep_id,
        "channel": "EMAIL",
        "destination": "vp@company.com",
        "recipient_name": "VP Commerce",
    }
    res_test = client.post("/api/v1/pulse/dispatch/test", json=test_dispatch_payload, headers=headers)
    assert res_test.status_code == 200
    assert res_test.json()["channel"] == "EMAIL"

    # 10. GET /deliveries
    res_deliv = client.get(f"/api/v1/pulse/deliveries?report_id={rep_id}", headers=headers)
    assert res_deliv.status_code == 200
    deliv_json = res_deliv.json()
    assert deliv_json["data"]["total_count"] >= 1

    # 11. POST /recipients/opt & GET /recipients
    opt_payload = {
        "channel": "WHATSAPP",
        "destination": "+14155559999",
        "opt_status": "OPTED_IN",
        "recipient_name": "Founder",
    }
    res_opt = client.post("/api/v1/pulse/recipients/opt", json=opt_payload, headers=headers)
    assert res_opt.status_code == 200
    assert res_opt.json()["opt_status"] == "OPTED_IN"

    res_recips = client.get("/api/v1/pulse/recipients", headers=headers)
    assert res_recips.status_code == 200
    assert len(res_recips.json()) >= 1

    # 12. DELETE /schedules/{schedule_id}
    res_del_sched = client.delete(f"/api/v1/pulse/schedules/{sched_id}", headers=headers)
    assert res_del_sched.status_code == 200
    assert res_del_sched.json()["success"] is True


def test_scheduler_persistence_and_timezone_handling(pulse_db_session: Session):
    """
    Test scheduler persistence across session restarts, multi-timezone normalization,
    idempotency, and duplicate trigger prevention.
    """
    session = pulse_db_session
    biz_id = "biz-pulse-timezone-persist"
    biz = _seed_pulse_tenant(session, biz_id, "Timezone Persist Merchant")

    scheduler = PulseScheduler()

    # 1. Multi-timezone calculations
    # Reference: 2023-06-01 00:00:00 UTC
    ref_dt = datetime(2023, 6, 1, 0, 0, tzinfo=UTC)

    # Asia/Kolkata is UTC+5:30. 09:00 IST corresponds to 03:30 UTC.
    next_ist = scheduler.calculate_next_run(
        frequency=ReportFrequency.DAILY,
        time_of_day="09:00",
        timezone_str="Asia/Kolkata",
        from_dt=ref_dt,
    )
    assert next_ist.hour == 3 and next_ist.minute == 30

    # America/New_York on June 1 is EDT (UTC-4). 08:00 EDT corresponds to 12:00 UTC.
    next_edt = scheduler.calculate_next_run(
        frequency=ReportFrequency.DAILY,
        time_of_day="08:00",
        timezone_str="America/New_York",
        from_dt=ref_dt,
    )
    assert next_edt.hour == 12 and next_edt.minute == 0

    # 2. Persistence across session restart
    sched = PulseReportSchedule(
        business_id=biz_id,
        organization_id=biz.organization_id,
        schedule_name="Persisted Global Schedule",
        report_type=ReportType.WEEKLY_MANAGEMENT.value,
        frequency=ReportFrequency.WEEKLY.value,
        day_of_week=0,  # Monday
        time_of_day="09:00",
        timezone="Asia/Kolkata",
        channel_types=[DeliveryChannel.EMAIL.value],
        recipients_json=[{"channel": "EMAIL", "destination": "gm@store.in", "name": "General Manager"}],
        kpi_categories=["financial", "customer"],
        is_enabled=True,
        next_run_at=datetime(2023, 6, 1, 3, 29, tzinfo=UTC),
    )
    session.add(sched)
    session.commit()
    sched_id = sched.id

    # Simulate process restart by rolling back and closing session
    session.rollback()
    reloaded_sched = session.get(PulseReportSchedule, sched_id)
    assert reloaded_sched is not None
    assert reloaded_sched.schedule_name == "Persisted Global Schedule"
    assert reloaded_sched.timezone == "Asia/Kolkata"
    assert reloaded_sched.is_enabled is True

    # 3. Idempotency & duplicate prevention
    trigger_dt = datetime(2023, 6, 1, 3, 31, tzinfo=UTC)
    run_1_ids = scheduler.process_due_schedules(session, as_of_time=trigger_dt)
    assert len(run_1_ids) == 1

    # Running immediately again at the exact same or slightly later timestamp
    # MUST NOT process the schedule again because next_run_at has been advanced forward!
    run_2_ids = scheduler.process_due_schedules(session, as_of_time=trigger_dt + timedelta(seconds=10))
    assert len(run_2_ids) == 0, "Schedule triggered twice! Duplicate prevention violation."

    # 4. Disabled schedule verification
    session.refresh(reloaded_sched)
    reloaded_sched.is_enabled = False
    reloaded_sched.next_run_at = datetime(2023, 6, 1, 0, 0, tzinfo=UTC)  # Past due
    session.commit()

    run_disabled_ids = scheduler.process_due_schedules(session, as_of_time=trigger_dt)
    assert len(run_disabled_ids) == 0, "Disabled schedule must not trigger."


def test_delivery_retry_and_audit_failure_recovery(pulse_db_session: Session):
    """
    Test delivery failure recording, retry mechanics with attempt increments,
    and recipient opt preferences management.
    """
    session = pulse_db_session
    biz_id = "biz-pulse-retry-audit"
    biz = _seed_pulse_tenant(session, biz_id, "Audit & Retry Merchant")

    # 1. Generate an initial report
    report = PulseService.generate_report(
        session=session,
        business_id=biz_id,
        report_type=ReportType.MONTHLY_EXECUTIVE,
        report_title="Audit & Retry Test Report",
    )
    assert report.id is not None

    # 2. Simulate an initial failed delivery attempt (e.g. timeout / network fault)
    failed_log = PulseDeliveryLog(
        report_id=report.id,
        business_id=biz_id,
        organization_id=biz.organization_id,
        channel=DeliveryChannel.WHATSAPP.value,
        recipient_destination="+14155550001",
        recipient_name="Operations Lead",
        status=DeliveryStatus.FAILED.value,
        attempts=1,
        error_message="Simulated upstream network timeout to WhatsApp Cloud API",
        dispatched_at=datetime.now(UTC) - timedelta(minutes=15),
    )
    session.add(failed_log)
    session.commit()
    log_id = failed_log.id

    # 3. Execute retry via PulseService.retry_delivery
    retried_item = PulseService.retry_delivery(
        session=session,
        business_id=biz_id,
        delivery_id=log_id,
    )

    # Verify attempts incremented and status transitioned to MOCKED/DELIVERED (via mock dispatcher)
    assert retried_item.attempts == 2
    assert retried_item.status == DeliveryStatus.MOCKED.value
    assert retried_item.external_message_id is not None
    assert retried_item.delivered_at is not None

    # 4. Verify recipient opt-in/opt-out toggling
    opt_req = PulseRecipientOptRequest(
        channel=DeliveryChannel.WHATSAPP,
        destination="+14155550001",
        recipient_name="Operations Lead",
        role="Manager",
        opt_status=RecipientOptStatus.OPTED_OUT,
        opt_out_reason="On annual leave",
    )
    recip = PulseService.register_or_update_recipient(session, biz_id, opt_req)
    assert recip.opt_status == RecipientOptStatus.OPTED_OUT.value
    assert recip.opt_out_reason == "On annual leave"

    # Verify listing preferences
    recipients = PulseService.list_recipients(session, biz_id)
    assert len(recipients) == 1
    assert recipients[0].destination == "+14155550001"
    assert recipients[0].opt_status == RecipientOptStatus.OPTED_OUT.value
