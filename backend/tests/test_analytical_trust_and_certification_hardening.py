"""
NEXUS Analytical Trust and Data Certification Hardening Tests.

Verifies:
1. Authoritative Watermark Certification State Machine (IMPORT_COMPLETED,
   LATEST_OBSERVED_DATE, SOURCE_COMPLETENESS_UNVERIFIED, SOURCE_COMPLETENESS_VERIFIED,
   PERIOD_CLOSE_CERTIFIED).
2. Actual versus Estimated Profitability Governance (ACTUAL, ESTIMATED, UNAVAILABLE).
3. Forecast Confidence and History Sufficiency Tiers (PRELIMINARY_RUN_RATE,
   EXPLORATORY_FORECAST, VALIDATED_STATISTICAL_FORECAST).
"""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from app.analytics.analyst.models import (
    ExecutionContext,
    SkillDomain,
    SkillExecutionResult,
)
from app.analytics.analyst.lead_analyst import LeadAnalyst
from app.analytics.analyst.orchestrator import ExecutionPlan, OrchestrationResult
from app.analytics.analyst.skills.commercial import GrossMarginAnalysisSkill
from app.analytics.analyst.skills.diagnostic import MarginVarianceSkill
from app.analytics.analyst.skills.predictive import TimeSeriesForecastingSkill
from app.analytics.customer.safety import (
    CadenceEligibilityStatus,
    CadenceSafetyGate,
    SafetyReasonCode,
)
from app.models.customer import Customer
from app.models.product import Product
from app.models.sale import Sale
from app.models.sale_item import SaleItem
from app.models.tenant import Business, Organization
from app.services.data_gateway_service import DataGatewayService
from app.services.watermark_service import (
    WatermarkCertificationState,
    WatermarkService,
)


@pytest.fixture
def hardening_biz(db_session: Session) -> Business:
    org = Organization(
        id=f"org_hard_{uuid4().hex[:6]}",
        name="Hardening Org",
        slug=f"hard-org-{uuid4().hex[:6]}",
    )
    db_session.add(org)
    db_session.flush()

    biz = Business(
        id=f"biz_hard_{uuid4().hex[:6]}",
        organization_id=org.id,
        name="Hardening Retail",
        status="active",
        currency="USD",
        timezone="UTC",
    )
    db_session.add(biz)
    db_session.commit()
    return biz


def _make_customer(db_session: Session, biz_id: str, code: str, name: str, email: str) -> Customer:
    cust = Customer(
        business_id=biz_id,
        customer_code=code,
        name=name,
        email=email,
        city="New York",
        customer_segment="Retail",
        acquisition_date=datetime.now(UTC).date(),
    )
    db_session.add(cust)
    db_session.flush()
    return cust


# ==============================================================================
# 1. WATERMARK CERTIFICATION STATE MACHINE & PERIOD CLOSE TESTS
# ==============================================================================


def test_watermark_certification_states_defined():
    """Verify all 5 distinct certification governance states exist."""
    states = {s.value for s in WatermarkCertificationState}
    assert "IMPORT_COMPLETED" in states
    assert "LATEST_OBSERVED_DATE" in states
    assert "SOURCE_COMPLETENESS_UNVERIFIED" in states
    assert "SOURCE_COMPLETENESS_VERIFIED" in states
    assert "PERIOD_CLOSE_CERTIFIED" in states


def test_import_completion_without_period_close_is_unverified(db_session: Session, hardening_biz: Business):
    """
    Import completion updates observed high-water mark, but retains
    SOURCE_COMPLETENESS_UNVERIFIED (provisional) without declaring period-close.
    """
    biz_id = hardening_biz.id
    now = datetime.now(UTC)
    tx_dates = [now - timedelta(days=5), now - timedelta(days=2), now - timedelta(days=1)]

    wm = WatermarkService.record_import_completion(
        session=db_session,
        business_id=biz_id,
        source_id="shopify_csv",
        transaction_dates=tx_dates,
        certified_complete_through=None,
    )
    assert wm is not None
    assert wm.verification_status == "provisional"
    assert (wm.metadata_json or {}).get("import_status") == WatermarkCertificationState.IMPORT_COMPLETED.value
    assert (wm.metadata_json or {}).get("governance_state") == WatermarkCertificationState.SOURCE_COMPLETENESS_UNVERIFIED.value
    assert (wm.metadata_json or {}).get("latest_observed_date") is not None

    eff_wm = WatermarkService.get_effective_tenant_watermark(session=db_session, business_id=biz_id)
    assert eff_wm.status in {"incomplete_watermark_gap", "unverified_provisional"}
    assert eff_wm.certification_state == WatermarkCertificationState.SOURCE_COMPLETENESS_UNVERIFIED.value
    assert eff_wm.is_verified is False

    # Safety gate must refuse actionability for unverified watermark
    verdict = CadenceSafetyGate.evaluate_tenant_safety(
        session=db_session,
        business_id=biz_id,
        as_of_date=now,
    )
    assert verdict.is_actionable is False
    assert verdict.eligibility_status == CadenceEligibilityStatus.DIAGNOSTIC_ONLY
    assert verdict.reason_code in {SafetyReasonCode.PROVISIONAL_WATERMARK, SafetyReasonCode.INCOMPLETE_SOURCE_BOUNDARIES}


def test_explicit_certified_complete_through_establishes_verified_state(db_session: Session, hardening_biz: Business):
    """Explicit authoritative certified_complete_through establishes SOURCE_COMPLETENESS_VERIFIED."""
    biz_id = hardening_biz.id
    now = datetime.now(UTC)

    wm = WatermarkService.record_import_completion(
        session=db_session,
        business_id=biz_id,
        source_id="certified_feed",
        transaction_dates=[now - timedelta(days=3)],
        certified_complete_through=now - timedelta(days=1),
    )
    assert wm is not None
    assert wm.verification_status == "verified"
    assert (wm.metadata_json or {}).get("governance_state") == WatermarkCertificationState.SOURCE_COMPLETENESS_VERIFIED.value

    eff_wm = WatermarkService.get_effective_tenant_watermark(session=db_session, business_id=biz_id)
    assert eff_wm.status == "verified_complete"
    assert eff_wm.certification_state == WatermarkCertificationState.SOURCE_COMPLETENESS_VERIFIED.value
    assert eff_wm.is_verified is True


def test_accounting_period_close_establishes_period_close_certified(db_session: Session, hardening_biz: Business):
    """Accounting period close establishes authoritative PERIOD_CLOSE_CERTIFIED."""
    biz_id = hardening_biz.id
    now = datetime.now(UTC)

    WatermarkService.record_watermark(
        session=db_session,
        contract={
            "business_id": biz_id,
            "source_id": "erp_ledger",
            "complete_through_dt": now - timedelta(days=1),
            "provenance_type": "accounting_period_close",
            "verification_status": "verified",
        },
    )

    eff_wm = WatermarkService.get_effective_tenant_watermark(session=db_session, business_id=biz_id)
    assert eff_wm.status == "verified_complete"
    assert eff_wm.certification_state == WatermarkCertificationState.PERIOD_CLOSE_CERTIFIED.value
    assert eff_wm.is_verified is True


# ==============================================================================
# 2. ACTUAL VERSUS ESTIMATED PROFITABILITY GOVERNANCE TESTS
# ==============================================================================


def test_auto_created_product_in_gateway_sets_zero_cost(db_session: Session, hardening_biz: Business):
    """DataGatewayService must not fabricate artificial 50% margins on missing product catalog."""
    biz_id = hardening_biz.id
    now = datetime.now(UTC)

    csv_content = (
        "order_id,date,amount,sku,status\n"
        f"ORD-TEST-999,{(now - timedelta(days=2)).strftime('%Y-%m-%d %H:%M:%S')},200.00,SKU-NEW999,completed\n"
    )

    dataset = DataGatewayService.save_raw_dataset(
        db=db_session,
        business_id=biz_id,
        organization_id=hardening_biz.organization_id,
        filename="new_sku.csv",
        content=csv_content.encode("utf-8"),
    )
    res = DataGatewayService.ingest_into_core_models(
        db=db_session,
        dataset_id=dataset.id,
        business_id=biz_id,
        target_entity="Sale",
    )
    assert res["records_persisted"] >= 1

    prod = db_session.query(Product).filter(Product.business_id == biz_id, Product.sku == "SKU-NEW999").first()
    assert prod is not None
    assert prod.name == "Uncataloged Product SKU-NEW999"
    assert prod.unit_cost == Decimal("0.00"), f"Expected 0.00 unit_cost, found {prod.unit_cost}"


def test_gross_margin_actual_classification_when_verified_costs_exist(db_session: Session, hardening_biz: Business):
    """When verified product catalog costs exist for all sold items, classification is ACTUAL."""
    biz_id = hardening_biz.id
    now = datetime.now(UTC)

    cust = _make_customer(db_session, biz_id, "C-VER-01", "Ver Cust", "ver@test.com")

    prod = Product(
        business_id=biz_id,
        sku="SKU-VERIFIED-1",
        name="Verified Widget",
        category="General",
        subcategory="General",
        selling_price=Decimal("100.00"),
        unit_cost=Decimal("40.00"),  # Verified 60% gross margin
        active=True,
    )
    db_session.add(prod)
    db_session.flush()

    sale = Sale(
        business_id=biz_id,
        transaction_number="S-VER-01",
        customer_id=cust.id,
        transaction_date=now - timedelta(days=3),
        subtotal=Decimal("100.00"),
        discount_amount=Decimal("0.00"),
        tax_amount=Decimal("0.00"),
        total_amount=Decimal("100.00"),
        status="completed",
    )
    db_session.add(sale)
    db_session.flush()

    s_item = SaleItem(
        sale=sale,
        product_id=prod.id,
        quantity=1,
        unit_price=Decimal("100.00"),
        line_total=Decimal("100.00"),
    )
    db_session.add(s_item)
    db_session.commit()

    ctx = ExecutionContext(business_id=biz_id, query="Margin check")
    skill = GrossMarginAnalysisSkill()
    res = skill.execute(db_session, ctx)

    assert res.status == "SUCCESS"
    assert res.data["cost_classification"] == "ACTUAL"
    assert res.data["estimation_method"] is None
    assert res.data["gross_profit"] == 60.00
    assert res.data["gross_margin_pct"] == 60.0


def test_gross_margin_estimated_classification_with_catalog_markup(db_session: Session, hardening_biz: Business):
    """When some sold items lack cost but catalog markup exists, classification is ESTIMATED."""
    biz_id = hardening_biz.id
    now = datetime.now(UTC)

    cust = _make_customer(db_session, biz_id, "C-EST-01", "Est Cust", "est@test.com")

    cat_prod = Product(
        business_id=biz_id,
        sku="SKU-CATALOG-REF",
        name="Reference Catalog Item",
        category="General",
        subcategory="General",
        selling_price=Decimal("200.00"),
        unit_cost=Decimal("100.00"),
        active=True,
    )
    un_prod = Product(
        business_id=biz_id,
        sku="SKU-UNRECORDED",
        name="Uncataloged Product SKU-UNRECORDED",
        category="General",
        subcategory="General",
        selling_price=Decimal("50.00"),
        unit_cost=Decimal("0.00"),
        active=True,
    )
    db_session.add_all([cat_prod, un_prod])
    db_session.flush()

    sale = Sale(
        business_id=biz_id,
        transaction_number="S-EST-01",
        customer_id=cust.id,
        transaction_date=now - timedelta(days=3),
        subtotal=Decimal("50.00"),
        discount_amount=Decimal("0.00"),
        tax_amount=Decimal("0.00"),
        total_amount=Decimal("50.00"),
        status="completed",
    )
    db_session.add(sale)
    db_session.flush()

    s_item = SaleItem(
        sale=sale,
        product_id=un_prod.id,
        quantity=1,
        unit_price=Decimal("50.00"),
        line_total=Decimal("50.00"),
    )
    db_session.add(s_item)
    db_session.commit()

    ctx = ExecutionContext(business_id=biz_id, query="Profit check")
    skill = GrossMarginAnalysisSkill()
    res = skill.execute(db_session, ctx)

    assert res.status == "SUCCESS"
    assert res.data["cost_classification"] == "ESTIMATED"
    assert res.data["estimation_method"] == "catalog_average_markup"
    assert res.data["cogs"] == 25.00
    assert res.data["gross_profit"] == 25.00
    assert res.data["gross_margin_pct"] == 50.0


def test_gross_margin_unavailable_when_no_cost_data_exists(db_session: Session, hardening_biz: Business):
    """When no cost data exists anywhere in catalog, classification is UNAVAILABLE."""
    biz_id = hardening_biz.id
    now = datetime.now(UTC)

    cust = _make_customer(db_session, biz_id, "C-NOC-01", "NoCost Cust", "noc@test.com")

    un_prod = Product(
        business_id=biz_id,
        sku="SKU-NO-COST",
        name="Uncataloged Product SKU-NO-COST",
        category="General",
        subcategory="General",
        selling_price=Decimal("80.00"),
        unit_cost=Decimal("0.00"),
        active=True,
    )
    db_session.add(un_prod)
    db_session.flush()

    sale = Sale(
        business_id=biz_id,
        transaction_number="S-NOC-01",
        customer_id=cust.id,
        transaction_date=now - timedelta(days=2),
        subtotal=Decimal("80.00"),
        discount_amount=Decimal("0.00"),
        tax_amount=Decimal("0.00"),
        total_amount=Decimal("80.00"),
        status="completed",
    )
    db_session.add(sale)
    db_session.flush()

    s_item = SaleItem(
        sale=sale,
        product_id=un_prod.id,
        quantity=1,
        unit_price=Decimal("80.00"),
        line_total=Decimal("80.00"),
    )
    db_session.add(s_item)
    db_session.commit()

    ctx = ExecutionContext(business_id=biz_id, query="Profit audit")
    skill = GrossMarginAnalysisSkill()
    res = skill.execute(db_session, ctx)

    assert res.status == "SUCCESS"
    assert res.data["cost_classification"] == "UNAVAILABLE"
    assert res.data["cogs"] is None
    assert res.data["gross_profit"] is None
    assert res.data["gross_margin_pct"] is None


def test_lead_analyst_profitability_executive_answer_prefix(db_session: Session, hardening_biz: Business):
    """Lead Analyst synthesis prefixes profitability answers with classification tags."""
    ctx = ExecutionContext(business_id=hardening_biz.id, query="audit profitability")
    plan = ExecutionPlan(
        query="audit margin",
        detected_intent="MARGIN_AND_PROFITABILITY_AUDIT",
        target_entities=[],
        selected_skill_ids=["gross_margin_analysis"],
        execution_order=["gross_margin_analysis"],
        routing_rationale="test",
    )

    # 1. ACTUAL
    res_actual = OrchestrationResult(
        plan=plan,
        skill_results={
            "gross_margin_analysis": SkillExecutionResult(
                skill_id="gross_margin_analysis",
                skill_name="Gross Margin Financial Analyst",
                domain=SkillDomain.COMMERCIAL,
                status="SUCCESS",
                findings=["Actual margin observed."],
                calculations=[],
                limitations=[],
                confidence_score=0.98,
                data={
                    "cost_classification": "ACTUAL",
                    "gross_profit": 500.0,
                    "gross_margin_pct": 50.0,
                    "cogs": 500.0,
                },
            )
        },
        conflicts=[],
        total_execution_time_ms=10.0,
    )
    report_actual = LeadAnalyst.reconcile_and_synthesize(res_actual, ctx)
    assert report_actual.executive_answer.startswith("[ACTUAL PROFITABILITY]")

    # 2. ESTIMATED
    res_est = OrchestrationResult(
        plan=plan,
        skill_results={
            "gross_margin_analysis": SkillExecutionResult(
                skill_id="gross_margin_analysis",
                skill_name="Gross Margin Financial Analyst",
                domain=SkillDomain.COMMERCIAL,
                status="SUCCESS",
                findings=["Estimated margin."],
                calculations=[],
                limitations=[],
                confidence_score=0.70,
                data={
                    "cost_classification": "ESTIMATED",
                    "estimation_method": "catalog_average_markup",
                    "gross_profit": 400.0,
                    "gross_margin_pct": 40.0,
                },
            )
        },
        conflicts=[],
        total_execution_time_ms=10.0,
    )
    report_est = LeadAnalyst.reconcile_and_synthesize(res_est, ctx)
    assert report_est.executive_answer.startswith("[ESTIMATED PROFITABILITY - Method: catalog_average_markup]")

    # 3. UNAVAILABLE
    res_un = OrchestrationResult(
        plan=plan,
        skill_results={
            "gross_margin_analysis": SkillExecutionResult(
                skill_id="gross_margin_analysis",
                skill_name="Gross Margin Financial Analyst",
                domain=SkillDomain.COMMERCIAL,
                status="SUCCESS",
                findings=["Unavailable."],
                calculations=[],
                limitations=[],
                confidence_score=0.0,
                data={"cost_classification": "UNAVAILABLE"},
            )
        },
        conflicts=[],
        total_execution_time_ms=10.0,
    )
    report_un = LeadAnalyst.reconcile_and_synthesize(res_un, ctx)
    assert report_un.executive_answer.startswith("[PROFITABILITY UNAVAILABLE]")


# ==============================================================================
# 3. THREE-TIER FORECAST CONFIDENCE & HISTORY SUFFICIENCY TESTS
# ==============================================================================


def test_forecast_tier1_preliminary_run_rate_under_14_days(db_session: Session, hardening_biz: Business):
    """
    Under 14 days of history:
    - Tier = PRELIMINARY_RUN_RATE
    - Confidence score <= 0.40
    - No manufactured Gaussian 95% CIs (low and high bounds are None)
    """
    biz_id = hardening_biz.id
    now = datetime.now(UTC)

    cust = _make_customer(db_session, biz_id, "C-FC-01", "Fc Cust", "fc1@test.com")

    for i in range(1, 7):
        db_session.add(
            Sale(
                business_id=biz_id,
                transaction_number=f"S-FC-T1-{i}",
                customer_id=cust.id,
                transaction_date=now - timedelta(days=i),
                subtotal=Decimal("100.00"),
                discount_amount=Decimal("0.00"),
                tax_amount=Decimal("0.00"),
                total_amount=Decimal("100.00"),
                status="completed",
            )
        )
    db_session.commit()

    ctx = ExecutionContext(business_id=biz_id, query="sales forecast")
    skill = TimeSeriesForecastingSkill()
    res = skill.execute(db_session, ctx)

    assert res.status == "SUCCESS"
    assert res.data["forecast_tier"] == "PRELIMINARY_RUN_RATE"
    assert res.data["history_days"] == 6
    assert res.data["projected_30d_baseline"] == 3000.00
    assert res.data["projected_30d_low"] is None
    assert res.data["projected_30d_high"] is None
    assert res.confidence_score <= 0.40


def test_forecast_tier2_exploratory_forecast_14_to_59_days(db_session: Session, hardening_biz: Business):
    """
    14–59 days of history:
    - Tier = EXPLORATORY_FORECAST
    - 7-day holdout backtest MAPE computed
    - Exploratory bounds set
    - Confidence score in [0.60, 0.75]
    """
    biz_id = hardening_biz.id
    now = datetime.now(UTC)

    cust = _make_customer(db_session, biz_id, "C-FC-02", "Fc Cust 2", "fc2@test.com")

    for i in range(1, 21):
        amt = Decimal(f"{100 + (i % 5) * 10}.00")
        db_session.add(
            Sale(
                business_id=biz_id,
                transaction_number=f"S-FC-T2-{i}",
                customer_id=cust.id,
                transaction_date=now - timedelta(days=i),
                subtotal=amt,
                discount_amount=Decimal("0.00"),
                tax_amount=Decimal("0.00"),
                total_amount=amt,
                status="completed",
            )
        )
    db_session.commit()

    ctx = ExecutionContext(business_id=biz_id, query="sales forecast")
    skill = TimeSeriesForecastingSkill()
    res = skill.execute(db_session, ctx)

    assert res.status == "SUCCESS"
    assert res.data["forecast_tier"] == "EXPLORATORY_FORECAST"
    assert res.data["history_days"] == 20
    assert res.data["backtest_mape"] is not None
    assert res.data["projected_30d_low"] is not None
    assert res.data["projected_30d_high"] is not None
    assert 0.60 <= res.confidence_score <= 0.75


def test_forecast_tier3_validated_statistical_forecast_60_plus_days(db_session: Session, hardening_biz: Business):
    """
    60+ days of history:
    - Tier = VALIDATED_STATISTICAL_FORECAST
    - Holdout backtest MAPE computed
    - Residual standard error 95% CIs
    - Confidence score in [0.85, 0.95]
    """
    biz_id = hardening_biz.id
    now = datetime.now(UTC)

    cust = _make_customer(db_session, biz_id, "C-FC-03", "Fc Cust 3", "fc3@test.com")

    for i in range(1, 66):
        amt = Decimal(f"{200 + (i % 10) * 15}.00")
        db_session.add(
            Sale(
                business_id=biz_id,
                transaction_number=f"S-FC-T3-{i}",
                customer_id=cust.id,
                transaction_date=now - timedelta(days=i),
                subtotal=amt,
                discount_amount=Decimal("0.00"),
                tax_amount=Decimal("0.00"),
                total_amount=amt,
                status="completed",
            )
        )
    db_session.commit()

    ctx = ExecutionContext(business_id=biz_id, query="sales forecast")
    skill = TimeSeriesForecastingSkill()
    res = skill.execute(db_session, ctx)

    assert res.status == "SUCCESS"
    assert res.data["forecast_tier"] == "VALIDATED_STATISTICAL_FORECAST"
    assert res.data["history_days"] == 65
    assert res.data["backtest_mape"] is not None
    assert res.data["projected_30d_low"] is not None
    assert res.data["projected_30d_high"] is not None
    assert 0.85 <= res.confidence_score <= 0.95


def test_lead_analyst_forecasting_executive_answer_prefix(db_session: Session, hardening_biz: Business):
    """Lead Analyst synthesis prefixes forecasting answers with tier tags."""
    ctx = ExecutionContext(business_id=hardening_biz.id, query="forecast")
    plan = ExecutionPlan(
        query="sales forecast",
        detected_intent="COMMERCIAL_FORECASTING",
        target_entities=[],
        selected_skill_ids=["time_series_forecasting"],
        execution_order=["time_series_forecasting"],
        routing_rationale="test",
    )

    # 1. PRELIMINARY_RUN_RATE
    res_t1 = OrchestrationResult(
        plan=plan,
        skill_results={
            "time_series_forecasting": SkillExecutionResult(
                skill_id="time_series_forecasting",
                skill_name="Time-Series Forecasting Analyst",
                domain=SkillDomain.PREDICTIVE,
                status="SUCCESS",
                findings=["Run rate."],
                calculations=[],
                limitations=[],
                confidence_score=0.35,
                data={
                    "forecast_tier": "PRELIMINARY_RUN_RATE",
                    "projected_30d_baseline": 3000.0,
                    "daily_run_rate": 100.0,
                    "history_days": 5,
                },
            )
        },
        conflicts=[],
        total_execution_time_ms=10.0,
    )
    report_t1 = LeadAnalyst.reconcile_and_synthesize(res_t1, ctx)
    assert report_t1.executive_answer.startswith("[PRELIMINARY RUN-RATE]")

    # 2. EXPLORATORY_FORECAST
    res_t2 = OrchestrationResult(
        plan=plan,
        skill_results={
            "time_series_forecasting": SkillExecutionResult(
                skill_id="time_series_forecasting",
                skill_name="Time-Series Forecasting Analyst",
                domain=SkillDomain.PREDICTIVE,
                status="SUCCESS",
                findings=["Exploratory forecast."],
                calculations=[],
                limitations=[],
                confidence_score=0.70,
                data={
                    "forecast_tier": "EXPLORATORY_FORECAST",
                    "projected_30d_baseline": 6000.0,
                    "projected_30d_low": 5000.0,
                    "projected_30d_high": 7000.0,
                    "backtest_mape": 12.5,
                },
            )
        },
        conflicts=[],
        total_execution_time_ms=10.0,
    )
    report_t2 = LeadAnalyst.reconcile_and_synthesize(res_t2, ctx)
    assert report_t2.executive_answer.startswith("[EXPLORATORY FORECAST]")

    # 3. VALIDATED_STATISTICAL_FORECAST
    res_t3 = OrchestrationResult(
        plan=plan,
        skill_results={
            "time_series_forecasting": SkillExecutionResult(
                skill_id="time_series_forecasting",
                skill_name="Time-Series Forecasting Analyst",
                domain=SkillDomain.PREDICTIVE,
                status="SUCCESS",
                findings=["Validated forecast."],
                calculations=[],
                limitations=[],
                confidence_score=0.90,
                data={
                    "forecast_tier": "VALIDATED_STATISTICAL_FORECAST",
                    "projected_30d_baseline": 15000.0,
                    "projected_30d_low": 13000.0,
                    "projected_30d_high": 17000.0,
                    "backtest_mape": 6.2,
                },
            )
        },
        conflicts=[],
        total_execution_time_ms=10.0,
    )
    report_t3 = LeadAnalyst.reconcile_and_synthesize(res_t3, ctx)
    assert report_t3.executive_answer.startswith("[VALIDATED STATISTICAL FORECAST]")
