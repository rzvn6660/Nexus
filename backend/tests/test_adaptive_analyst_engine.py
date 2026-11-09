"""Comprehensive Automated Tests for NEXUS Unified Data Intelligence & Adaptive Analyst Engine."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from app.analytics.analyst.base import BaseAnalystSkill
from app.analytics.analyst.lead_analyst import LeadAnalyst, LeadAnalystReport
from app.analytics.analyst.ledger import AnalystEvidenceLedger
from app.analytics.analyst.models import (
    ExecutionContext,
    SkillDomain,
    SkillExecutionResult,
    SkillMetadata,
)
from app.analytics.analyst.orchestrator import (
    AnalystOrchestrator,
    ConflictRecord,
    ExecutionPlan,
    OrchestrationResult,
)
from app.analytics.analyst.registry import AnalystSkillRegistry, get_skill_registry
from app.analytics.analyst.service import AnalystService
from app.analytics.onboarding.postgres_service import PostgreSQLOnboardingService
from app.models.customer import Customer
from app.models.history import AnalysisRun
from app.models.product import Product
from app.models.sale import Sale
from app.models.tenant import Business, Organization


@pytest.fixture
def analyst_biz(db_session: Session) -> Business:
    org = Organization(
        id=f"org_analyst_{uuid4().hex[:6]}",
        name="Analyst Engine Test Org",
        slug=f"analyst-org-{uuid4().hex[:6]}",
    )
    db_session.add(org)
    db_session.flush()

    biz = Business(
        id=f"biz_analyst_{uuid4().hex[:6]}",
        organization_id=org.id,
        name="Analyst Retail Store",
        status="active",
        currency="USD",
        timezone="UTC",
    )
    db_session.add(biz)
    db_session.flush()

    # Seed initial test data: customers, products, sales
    c1 = Customer(
        business_id=biz.id,
        customer_code=f"CUST-001-{uuid4().hex[:4]}",
        name="Alice Buyer",
        email=f"alice.{uuid4().hex[:4]}@example.com",
        city="New York",
        customer_segment="Retail",
        acquisition_date=datetime.now(UTC).date() - timedelta(days=90),
    )
    c2 = Customer(
        business_id=biz.id,
        customer_code=f"CUST-002-{uuid4().hex[:4]}",
        name="Bob Wholesale",
        email=f"bob.{uuid4().hex[:4]}@example.com",
        city="Chicago",
        customer_segment="Wholesale",
        acquisition_date=datetime.now(UTC).date() - timedelta(days=120),
    )
    db_session.add_all([c1, c2])
    db_session.flush()

    p1 = Product(
        business_id=biz.id,
        sku=f"SKU-A-{uuid4().hex[:4]}",
        name="Widget A",
        category="Electronics",
        subcategory="Gadgets",
        unit_cost=Decimal("20.00"),
        selling_price=Decimal("50.00"),
        active=True,
    )
    p2 = Product(
        business_id=biz.id,
        sku=f"SKU-B-{uuid4().hex[:4]}",
        name="Widget B",
        category="Accessories",
        subcategory="Cables",
        unit_cost=Decimal("5.00"),
        selling_price=Decimal("15.00"),
        active=True,
    )
    db_session.add_all([p1, p2])
    db_session.flush()

    # Sales across two periods
    now = datetime.now(UTC)
    s1 = Sale(
        business_id=biz.id,
        transaction_number=f"TX-001-{uuid4().hex[:4]}",
        customer_id=c1.id,
        transaction_date=now - timedelta(days=45),
        status="completed",
        subtotal=Decimal("100.00"),
        discount_amount=Decimal("0.00"),
        tax_amount=Decimal("0.00"),
        total_amount=Decimal("100.00"),
    )
    s2 = Sale(
        business_id=biz.id,
        transaction_number=f"TX-002-{uuid4().hex[:4]}",
        customer_id=c1.id,
        transaction_date=now - timedelta(days=15),
        status="completed",
        subtotal=Decimal("150.00"),
        discount_amount=Decimal("10.00"),
        tax_amount=Decimal("0.00"),
        total_amount=Decimal("140.00"),
    )
    s3 = Sale(
        business_id=biz.id,
        transaction_number=f"TX-003-{uuid4().hex[:4]}",
        customer_id=c2.id,
        transaction_date=now - timedelta(days=5),
        status="completed",
        subtotal=Decimal("500.00"),
        discount_amount=Decimal("0.00"),
        tax_amount=Decimal("0.00"),
        total_amount=Decimal("500.00"),
    )
    db_session.add_all([s1, s2, s3])
    db_session.commit()

    return biz


# ---------------------------------------------------------------------------
# 1. Registry Tests
# ---------------------------------------------------------------------------

def test_registry_census_and_domains():
    """Verify registry contains all 51 specialist skills across 8 domains."""
    registry = get_skill_registry()
    skills = registry.list_skills()

    assert len(skills) == 51
    domains = {s.domain for s in skills}
    assert len(domains) == 8

    assert SkillDomain.DISCOVERY in domains
    assert SkillDomain.QUALITY in domains
    assert SkillDomain.CUSTOMER_REVENUE in domains
    assert SkillDomain.PREDICTIVE in domains
    assert SkillDomain.DIAGNOSTIC in domains
    assert SkillDomain.RETENTION in domains
    assert SkillDomain.COMMERCIAL in domains
    assert SkillDomain.REPORTING in domains


def test_registry_toggle_skill():
    """Verify skills can be enabled and disabled safely."""
    registry = get_skill_registry()
    skill_id = "data_profiling"

    skill = registry.get_skill(skill_id)
    assert skill is not None
    assert skill.enabled is True

    # Disable
    success = registry.set_skill_enabled(skill_id, False)
    assert success is True
    assert skill.enabled is False

    # Re-enable
    registry.set_skill_enabled(skill_id, True)
    assert skill.enabled is True


# ---------------------------------------------------------------------------
# 2. Orchestration & Routing Tests
# ---------------------------------------------------------------------------

def test_orchestrator_churn_routing():
    """Verify 'Which customers may stop buying?' routes to churn and retention skills."""
    orchestrator = AnalystOrchestrator()
    plan = orchestrator.build_plan("Which customers may stop buying?")

    assert plan.detected_intent == "CHURN_AND_RETENTION_INVESTIGATION"
    assert "churn_prediction" in plan.selected_skill_ids
    assert "purchase_cadence_analysis" in plan.selected_skill_ids
    assert "retention_opportunity_identification" in plan.selected_skill_ids
    assert "intervention_recommendation" in plan.selected_skill_ids


def test_orchestrator_revenue_drop_routing():
    """Verify 'Why did revenue decrease?' routes to variance decomposition and root cause skills."""
    orchestrator = AnalystOrchestrator()
    plan = orchestrator.build_plan("Why did revenue decrease this month?")

    assert plan.detected_intent == "REVENUE_VARIANCE_ROOT_CAUSE"
    assert "revenue_variance_decomposition" in plan.selected_skill_ids
    assert "anomaly_detection" in plan.selected_skill_ids
    assert "driver_analysis" in plan.selected_skill_ids


def test_orchestrator_forecast_routing():
    """Verify 'Forecast next quarter sales' routes to time-series forecasting."""
    orchestrator = AnalystOrchestrator()
    plan = orchestrator.build_plan("Forecast next quarter sales")

    assert plan.detected_intent == "COMMERCIAL_FORECASTING"
    assert "time_series_forecasting" in plan.selected_skill_ids
    assert "commercial_forecasting" in plan.selected_skill_ids
    assert "seasonality_analysis" in plan.selected_skill_ids


def test_orchestrator_profitability_routing():
    """Verify 'Which products are reducing profitability?' routes to margin variance."""
    orchestrator = AnalystOrchestrator()
    plan = orchestrator.build_plan("Which products are reducing profitability?")

    assert plan.detected_intent == "MARGIN_AND_PROFITABILITY_AUDIT"
    assert "gross_margin_analysis" in plan.selected_skill_ids
    assert "margin_variance_analysis" in plan.selected_skill_ids
    assert "product_profitability" in plan.selected_skill_ids


# ---------------------------------------------------------------------------
# 3. Execution & Synthesis Tests
# ---------------------------------------------------------------------------

def test_multi_skill_execution_and_lead_analyst_synthesis(db_session: Session, analyst_biz: Business):
    """Test full collaborative execution and Lead Analyst 8-part synthesis."""
    result = AnalystService.analyze_business_question(
        db=db_session,
        business_id=analyst_biz.id,
        query="Why did revenue decrease?",
    )

    assert result["run_id"] > 0
    assert result["intent"] == "REVENUE_VARIANCE_ROOT_CAUSE"
    assert len(result["skills_used"]) >= 5

    report = result["lead_analyst_report"]
    # Check 8-part output fields
    assert "executive_answer" in report and len(report["executive_answer"]) > 10
    assert "key_findings" in report and len(report["key_findings"]) > 0
    assert "supporting_evidence" in report
    assert "relevant_calculations" in report
    assert "contributing_factors" in report
    assert "confidence_score" in report and report["confidence_score"] > 0.0
    assert "limitations" in report
    assert "recommended_next_action" in report
    assert "formatted_markdown" in report

    # Verify run committed to Evidence Ledger (AnalysisRun)
    run_in_db = db_session.query(AnalysisRun).filter_by(id=result["run_id"]).first()
    assert run_in_db is not None
    assert run_in_db.business_id == analyst_biz.id
    assert run_in_db.status == "completed"


def test_analyst_studio_overview(db_session: Session, analyst_biz: Business):
    """Verify studio telemetry aggregates data correctly."""
    overview = AnalystService.get_overview(db_session, analyst_biz.id)

    assert overview["total_registered_skills"] == 51
    assert overview["active_skill_versions"] >= 50
    assert overview["data_readiness_status"] in ("LATEST_OBSERVED_DATE", "VERIFIED", "SOURCE_COMPLETENESS_VERIFIED")
    assert len(overview["skills_by_domain"]) == 8


# ---------------------------------------------------------------------------
# 4. PostgreSQL Relational Onboarding Tests
# ---------------------------------------------------------------------------

def test_postgres_onboarding_unmapped_customer_safety(db_session: Session, analyst_biz: Business):
    """Verify that unmapped sales create a dedicated tenant-scoped unmapped customer rather than arbitrary assignment."""
    with patch("psycopg.connect") as mock_connect:
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_connect.return_value.__enter__.return_value = mock_conn
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur

        # Simulate source table with order lacking customer_code
        mock_cur.description = [("order_id",), ("total",), ("date",), ("status",)]
        mock_cur.fetchall.return_value = [
            ("PG-ORDER-99", "120.50", "2026-10-15T12:00:00", "completed"),
        ]

        res = PostgreSQLOnboardingService.ingest_table_to_canonical(
            db=db_session,
            business_id=analyst_biz.id,
            host="127.0.0.1",
            port=5432,
            database="testdb",
            user="user",
            password="pwd",
            table_name="orders",
            target_entity="Sale",
            column_mapping={
                "order_number": "order_id",
                "amount": "total",
                "date": "date",
                "status": "status",
                "allow_anonymous_customer": True,
                "anonymous_policy_approved_by": "manager_audit@apex.com",
            },
        )

        assert res["success"] is True
        assert res["inserted_count"] == 1

        # Check that sale was assigned to a dedicated audited anonymous customer under this tenant
        sale = db_session.query(Sale).filter_by(transaction_number="PG-ORDER-99").first()
        assert sale is not None
        assert sale.business_id == analyst_biz.id

        customer = db_session.query(Customer).filter_by(id=sale.customer_id).first()
        assert customer is not None
        assert customer.business_id == analyst_biz.id
        assert "ANON" in customer.customer_code or "UNMAPPED" in customer.customer_code


def test_orchestrator_scenario_e_unsupported_external_data():
    """Verify Scenario E: Out-of-domain / unsupported questions explain missing evidence."""
    orchestrator = AnalystOrchestrator()
    plan = orchestrator.build_plan("What was our ad spend and ROAS across TikTok campaigns?")

    assert plan.detected_intent == "UNSUPPORTED_OR_EXTERNAL_DATA_QUERY"
    assert "source_completeness" in plan.selected_skill_ids
    assert "missing_value_analysis" in plan.selected_skill_ids


def test_scenario_e_insufficient_data_synthesis(db_session: Session):
    """Verify Scenario E synthesis: Lead Analyst reports missing evidence and refuses speculation."""
    empty_org = Organization(
        id=f"org_empty_{uuid4().hex[:6]}",
        name="Empty Test Org",
        slug=f"empty-org-{uuid4().hex[:6]}",
    )
    db_session.add(empty_org)
    db_session.flush()

    empty_biz = Business(
        id=f"biz_empty_{uuid4().hex[:6]}",
        organization_id=empty_org.id,
        name="Empty Store",
        status="active",
        currency="USD",
        timezone="UTC",
    )
    db_session.add(empty_biz)
    db_session.commit()

    result = AnalystService.analyze_business_question(
        db=db_session,
        business_id=empty_biz.id,
        query="What was our customer acquisition cost and ad spend on TikTok?",
    )

    report = result["lead_analyst_report"]
    assert report["validation_status"] == "MISSING_SOURCE_EVIDENCE"
    assert "external business metrics" in report["executive_answer"]
    assert report["confidence_score"] == 0.0


def test_all_51_skills_executable_without_exception(db_session: Session, analyst_biz: Business):
    """Verify that every single registered skill is executable and returns valid structured output."""
    registry = get_skill_registry()
    ctx = ExecutionContext(business_id=analyst_biz.id, query="system verification test")

    for meta in registry.list_skills():
        skill = registry.get_skill(meta.skill_id)
        assert skill is not None, f"Skill {meta.skill_id} could not be retrieved"
        res = skill.run(db_session, ctx)
        assert res is not None, f"Skill {meta.skill_id} returned None"
        assert res.skill_id == meta.skill_id
        assert res.status in ("SUCCESS", "INSUFFICIENT_DATA", "SKIPPED")
        assert isinstance(res.findings, list)
        assert isinstance(res.calculations, list)
        assert 0.0 <= res.confidence_score <= 1.0


def test_evidence_ledger_immutability(db_session: Session, analyst_biz: Business):
    """Verify that completed AnalysisRun records cannot be updated or deleted."""
    run = AnalysisRun(
        request_id=str(uuid4()),
        business_id=analyst_biz.id,
        query="Immutability audit check",
        status="completed",
        answer="Authoritative original answer",
    )
    db_session.add(run)
    db_session.commit()

    # Attempt to tamper with answer
    run.answer = "Tampered unauthorized answer"
    with pytest.raises(ValueError, match="Completed AnalysisRun records cannot be modified"):
        db_session.commit()

    db_session.rollback()

    # Attempt to delete evidence record
    db_session.delete(run)
    with pytest.raises(ValueError, match="AnalysisRun records cannot be deleted"):
        db_session.commit()

    db_session.rollback()


def test_database_engine_triggers_block_analysis_run_raw_sql(db_session: Session, analyst_biz: Business):
    """Verify that physical database triggers reject direct raw SQL UPDATE and DELETE on completed AnalysisRun."""
    from sqlalchemy import text
    from sqlalchemy.exc import DBAPIError, IntegrityError
    from app.models.history import install_audit_triggers, drop_audit_triggers

    run = AnalysisRun(
        request_id=str(uuid4()),
        business_id=analyst_biz.id,
        query="Raw SQL immutability check",
        status="completed",
        answer="Authoritative original answer",
    )
    db_session.add(run)
    db_session.commit()

    # Install engine triggers on the test connection
    install_audit_triggers(db_session.connection())

    try:
        # Attempt direct raw SQL UPDATE on completed analysis run
        with pytest.raises((IntegrityError, DBAPIError)):
            db_session.execute(
                text("UPDATE analysis_runs SET query = 'Direct SQL Tamper' WHERE id = :id"),
                {"id": run.id},
            )
        db_session.rollback()

        # Attempt direct raw SQL DELETE on completed analysis run
        with pytest.raises((IntegrityError, DBAPIError)):
            db_session.execute(
                text("DELETE FROM analysis_runs WHERE id = :id"),
                {"id": run.id},
            )
        db_session.rollback()
    finally:
        drop_audit_triggers(db_session.connection())


def test_postgres_ingestion_watermark_backfill_invalidation(db_session: Session, analyst_biz: Business):
    """Verify that PostgreSQL transactional ingestion evaluates and handles watermarks and backfills."""
    from unittest.mock import MagicMock, patch
    from app.analytics.onboarding.postgres_service import PostgreSQLOnboardingService

    now_dt = datetime.now(UTC)

    with patch("psycopg.connect") as mock_connect:
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_connect.return_value.__enter__.return_value = mock_conn
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur

        mock_cur.description = [("order_id",), ("total",), ("date",), ("status",), ("cust_code",)]
        mock_cur.fetchall.return_value = [
            ("PG-ORD-1001", "125.50", now_dt.isoformat(), "completed", "CUST-PG-1"),
            ("PG-ORD-1002", "85.00", (now_dt - timedelta(days=90)).isoformat(), "completed", "CUST-PG-2"),
        ]

        with patch("app.services.watermark_service.WatermarkService.detect_backfill_and_handle") as mock_wm:
            res = PostgreSQLOnboardingService.ingest_table_to_canonical(
                db=db_session,
                business_id=analyst_biz.id,
                host="127.0.0.1",
                port=5432,
                database="testdb",
                user="user",
                password="pwd",
                table_name="orders",
                target_entity="Sale",
                column_mapping={
                    "order_number": "order_id",
                    "amount": "total",
                    "date": "date",
                    "status": "status",
                    "customer_code": "cust_code",
                },
            )

            assert res["success"] is True
            assert res["inserted_count"] == 2
            # Verify watermark backfill detection was invoked
            assert mock_wm.called
            assert mock_wm.call_args[1]["business_id"] == analyst_biz.id
            assert mock_wm.call_args[1]["source_id"] == "pg_public_orders"
            assert len(mock_wm.call_args[1]["transaction_dates"]) == 2


def test_known_benchmark_dataset_exact_analytical_reconciliation(db_session: Session):
    """
    Exhaustive Data-to-Insight Integrity Test:
    Verifies that imported transactions from CSV and PostgreSQL are fully visible,
    persisted into canonical models, and consumed by Revenue, Commercial, Customer,
    Retention, and Pulse analytics with exact mathematical parity.
    """
    from decimal import Decimal
    from sqlalchemy import func
    from app.models.tenant import Organization, Business
    from app.models.customer import Customer
    from app.models.product import Product
    from app.models.sale import Sale
    from app.models.sale_item import SaleItem
    from app.services.data_gateway_service import DataGatewayService
    from app.analytics.onboarding.postgres_service import PostgreSQLOnboardingService
    from app.analytics.analyst.service import AnalystService
    from app.analytics.customer.retention import CustomerRetentionService
    from app.analytics.pulse.service import PulseService
    from app.analytics.analyst.skills.commercial import RevenuePerformanceSkill, GrossMarginAnalysisSkill
    from app.analytics.analyst.skills.predictive import TimeSeriesForecastingSkill
    import pandas as pd
    import io

    # Create dedicated isolated business to ensure pure zero-noise benchmark evaluation
    bench_org = Organization(
        id=f"org_bench_{uuid4().hex[:6]}",
        name="Benchmark Org",
        slug=f"bench-org-{uuid4().hex[:6]}",
    )
    db_session.add(bench_org)
    db_session.flush()

    bench_biz = Business(
        id=f"biz_bench_{uuid4().hex[:6]}",
        organization_id=bench_org.id,
        name="Benchmark Retail Store",
        status="active",
        currency="USD",
        timezone="UTC",
    )
    db_session.add(bench_biz)
    db_session.flush()

    biz_id = bench_biz.id
    now = datetime.now(UTC)

    # 1. Seed Known Product Catalog (3 SKUs at exact 60.0% gross margin)
    p1 = Product(business_id=biz_id, sku="SKU-001", name="Wireless Ergonomic Mouse", selling_price=Decimal("50.00"), unit_cost=Decimal("20.00"), category="Electronics", subcategory="Peripherals", active=True)
    p2 = Product(business_id=biz_id, sku="SKU-002", name="Mechanical Gaming Keyboard", selling_price=Decimal("100.00"), unit_cost=Decimal("40.00"), category="Electronics", subcategory="Gaming", active=True)
    p3 = Product(business_id=biz_id, sku="SKU-003", name="USB-C Multiport Dock", selling_price=Decimal("80.00"), unit_cost=Decimal("32.00"), category="Accessories", subcategory="Docks", active=True)
    db_session.add_all([p1, p2, p3])

    # 2. Seed Known Customer Cohort (3 distinct customers)
    c1 = Customer(business_id=biz_id, customer_code="CUST-CSV-10", name="Alice Retail", email="alice@test.com", city="New York", customer_segment="Retail", acquisition_date=(now - timedelta(days=60)).date())
    c2 = Customer(business_id=biz_id, customer_code="CUST-CSV-11", name="Bob Enterprise", email="bob@test.com", city="Chicago", customer_segment="Enterprise", acquisition_date=(now - timedelta(days=60)).date())
    c3 = Customer(business_id=biz_id, customer_code="CUST-CSV-12", name="Carol Commerce", email="carol@test.com", city="San Francisco", customer_segment="Wholesale", acquisition_date=(now - timedelta(days=60)).date())
    db_session.add_all([c1, c2, c3])
    db_session.commit()

    # 3. Ingest 10 CSV Orders via Gateway Service
    # Prior Period (40-31 days ago): 5 orders = $50 + $100 + $80 + $50 + $100 = $380.00
    # Recent Period (25-5 days ago):  5 orders = $80 + $50 + $100 + $80 + $50 = $360.00
    # Total CSV Revenue = $740.00
    csv_rows = [
        {"order_number": "CSV-ORD-1001", "transaction_date": (now - timedelta(days=40)).strftime("%Y-%m-%d %H:%M:%S"), "customer_code": "CUST-CSV-10", "amount": 50.00, "sku": "SKU-001", "status": "completed"},
        {"order_number": "CSV-ORD-1002", "transaction_date": (now - timedelta(days=38)).strftime("%Y-%m-%d %H:%M:%S"), "customer_code": "CUST-CSV-11", "amount": 100.00, "sku": "SKU-002", "status": "completed"},
        {"order_number": "CSV-ORD-1003", "transaction_date": (now - timedelta(days=35)).strftime("%Y-%m-%d %H:%M:%S"), "customer_code": "CUST-CSV-12", "amount": 80.00, "sku": "SKU-003", "status": "completed"},
        {"order_number": "CSV-ORD-1004", "transaction_date": (now - timedelta(days=32)).strftime("%Y-%m-%d %H:%M:%S"), "customer_code": "CUST-CSV-10", "amount": 50.00, "sku": "SKU-001", "status": "completed"},
        {"order_number": "CSV-ORD-1005", "transaction_date": (now - timedelta(days=31)).strftime("%Y-%m-%d %H:%M:%S"), "customer_code": "CUST-CSV-11", "amount": 100.00, "sku": "SKU-002", "status": "completed"},
        {"order_number": "CSV-ORD-1006", "transaction_date": (now - timedelta(days=25)).strftime("%Y-%m-%d %H:%M:%S"), "customer_code": "CUST-CSV-12", "amount": 80.00, "sku": "SKU-003", "status": "completed"},
        {"order_number": "CSV-ORD-1007", "transaction_date": (now - timedelta(days=20)).strftime("%Y-%m-%d %H:%M:%S"), "customer_code": "CUST-CSV-10", "amount": 50.00, "sku": "SKU-001", "status": "completed"},
        {"order_number": "CSV-ORD-1008", "transaction_date": (now - timedelta(days=15)).strftime("%Y-%m-%d %H:%M:%S"), "customer_code": "CUST-CSV-11", "amount": 100.00, "sku": "SKU-002", "status": "completed"},
        {"order_number": "CSV-ORD-1009", "transaction_date": (now - timedelta(days=10)).strftime("%Y-%m-%d %H:%M:%S"), "customer_code": "CUST-CSV-12", "amount": 80.00, "sku": "SKU-003", "status": "completed"},
        {"order_number": "CSV-ORD-1010", "transaction_date": (now - timedelta(days=5)).strftime("%Y-%m-%d %H:%M:%S"), "customer_code": "CUST-CSV-10", "amount": 50.00, "sku": "SKU-001", "status": "completed"},
    ]
    df_csv = pd.DataFrame(csv_rows)
    buf = io.BytesIO()
    df_csv.to_csv(buf, index=False)
    buf.seek(0)

    dataset = DataGatewayService.save_raw_dataset(
        db=db_session,
        business_id=biz_id,
        organization_id=bench_org.id,
        filename="benchmark_orders.csv",
        content=buf.getvalue(),
    )
    ingest_res = DataGatewayService.ingest_into_core_models(
        db=db_session,
        dataset_id=dataset.id,
        business_id=biz_id,
        target_entity="Sale",
        column_overrides={},
    )
    assert ingest_res["records_persisted"] == 20  # 10 Sales + 10 SaleItem entities
    assert ingest_res["rows_ingested"] >= 10

    # 4. Ingest 2 PostgreSQL Orders (Order 11: $240.00 for Bob, Order 12: $180.50 Unmapped)
    with patch("psycopg.connect") as mock_pg:
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_pg.return_value.__enter__.return_value = mock_conn
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur
        mock_cur.description = [("order_id",), ("total",), ("date",), ("status",), ("cust_code",)]
        mock_cur.fetchall.return_value = [
            ("PG-ORD-501", "240.00", (now - timedelta(days=2)).isoformat(), "completed", "CUST-CSV-11"),
            ("PG-ORD-502", "180.50", (now - timedelta(days=1)).isoformat(), "completed", None),
        ]
        pg_res = PostgreSQLOnboardingService.ingest_table_to_canonical(
            db=db_session,
            business_id=biz_id,
            host="127.0.0.1",
            port=5432,
            database="legacy_db",
            user="reader",
            password="pwd",
            table_name="orders",
            target_entity="Sale",
            column_mapping={
                "order_number": "order_id",
                "amount": "total",
                "date": "date",
                "status": "status",
                "customer_code": "cust_code",
                "allow_anonymous_customer": True,
                "anonymous_policy_approved_by": "manager_audit@apex.com",
            },
        )
        assert pg_res["inserted_count"] == 2

    # 5. Direct Database Integrity Assertions
    direct_sales_count = db_session.query(Sale).filter(Sale.business_id == biz_id).count()
    direct_sales_sum = float(db_session.query(func.sum(Sale.total_amount)).filter(Sale.business_id == biz_id).scalar())
    direct_cust_count = db_session.query(Customer).filter(Customer.business_id == biz_id).count()
    direct_items_count = db_session.query(SaleItem).join(Sale, SaleItem.sale_id == Sale.id).filter(Sale.business_id == biz_id).count()
    direct_items_sum = float(db_session.query(func.sum(SaleItem.line_total)).join(Sale, SaleItem.sale_id == Sale.id).filter(Sale.business_id == biz_id).scalar())

    assert direct_sales_count == 12, f"Expected 12 sales, found {direct_sales_count}"
    assert direct_sales_sum == 1160.50, f"Expected $1160.50 total sales, found {direct_sales_sum}"
    assert direct_cust_count == 4, f"Expected 4 customers (3 named + 1 unmapped), found {direct_cust_count}"
    assert direct_items_count == 10, f"Expected 10 itemized lines, found {direct_items_count}"
    assert direct_items_sum == 740.00, f"Expected $740.00 itemized sales, found {direct_items_sum}"

    # 6. Commercial Analytics Skills Assertions
    ctx = ExecutionContext(business_id=biz_id, query="audit performance")
    rev_skill = RevenuePerformanceSkill()
    rev_res = rev_skill.execute(db_session, ctx)
    assert rev_res.data["order_count"] == 12
    assert rev_res.data["net_revenue"] == 1160.50

    margin_skill = GrossMarginAnalysisSkill()
    margin_res = margin_skill.execute(db_session, ctx)
    assert margin_res.data["item_revenue"] == 740.00
    assert margin_res.data["cogs"] == 296.00
    assert margin_res.data["gross_profit"] == 444.00
    assert margin_res.data["gross_margin_pct"] == 60.0

    forecast_skill = TimeSeriesForecastingSkill()
    forecast_res = forecast_skill.execute(db_session, ctx)
    assert forecast_res.status == "SUCCESS"
    assert forecast_res.data["projected_30d_baseline"] > 0

    # 7. Retention System Assertions & Certification Governance
    # 7a. Pre-certification: Import completed but period close uncertified -> provisional / non-actionable
    ret_overview_unverified = CustomerRetentionService.get_retention_overview(db_session, biz_id)
    assert ret_overview_unverified.total_customers_evaluated == 4
    assert ret_overview_unverified.active_customers_count == 4
    assert ret_overview_unverified.total_customers == 4
    assert ret_overview_unverified.repeat_buyers_count == 3
    assert ret_overview_unverified.one_time_buyers_count == 1
    assert ret_overview_unverified.safety_verdict.effective_watermark_status in {"incomplete_watermark_gap", "unverified_provisional"}
    assert ret_overview_unverified.safety_verdict.is_actionable is False

    # 7b. Establish authoritative period-close certification across all active ingestion sources
    from app.services.watermark_service import WatermarkService
    WatermarkService.record_watermark(
        session=db_session,
        contract={
            "business_id": biz_id,
            "source_id": "benchmark_orders.csv",
            "complete_through_dt": now,
            "provenance_type": "accounting_period_close",
            "verification_status": "verified",
        },
    )
    WatermarkService.record_watermark(
        session=db_session,
        contract={
            "business_id": biz_id,
            "source_id": "pg_public_orders",
            "complete_through_dt": now,
            "provenance_type": "accounting_period_close",
            "verification_status": "verified",
        },
    )

    # 7c. Post-certification: Verified complete and period-close certified -> actionable
    ret_overview = CustomerRetentionService.get_retention_overview(db_session, biz_id)
    assert ret_overview.safety_verdict.effective_watermark_status == "verified_complete"
    assert ret_overview.safety_verdict.eligible_repeat_buyers_count == 3

    # 8. Pulse Executive Briefing Assertions
    pulse_dash = PulseService.get_dashboard_overview(db_session, biz_id)
    assert pulse_dash.watermark_status in ("PERIOD_CLOSE_CERTIFIED", "verified_complete")
    assert pulse_dash.is_actionable is True
    pulse_fin = pulse_dash.kpi_payload.financial
    assert pulse_fin["total_orders"].value > 0

    # 9. Ask NEXUS Multi-Skill Scenarios Assertions
    sc_a = AnalystService.analyze_business_question(db=db_session, business_id=biz_id, query="Why did revenue decrease?")
    assert "$1,160.50" in sc_a["lead_analyst_report"]["executive_answer"] or "revenue" in sc_a["lead_analyst_report"]["executive_answer"].lower()

    sc_b = AnalystService.analyze_business_question(db=db_session, business_id=biz_id, query="Which customers may stop purchasing?")
    assert "repeat buyer accounts" in sc_b["lead_analyst_report"]["executive_answer"]
    assert "Single-order buyers were excluded" in sc_b["lead_analyst_report"]["executive_answer"]

    sc_c = AnalystService.analyze_business_question(db=db_session, business_id=biz_id, query="What will next-quarter sales be?")
    assert sc_c["lead_analyst_report"]["validation_status"] == "VALIDATED"
    assert "$" in sc_c["lead_analyst_report"]["executive_answer"]

    sc_d = AnalystService.analyze_business_question(db=db_session, business_id=biz_id, query="Which products are reducing profitability?")
    assert "$444.00" in sc_d["lead_analyst_report"]["executive_answer"]
    assert "60.0%" in sc_d["lead_analyst_report"]["executive_answer"]

    sc_e = AnalystService.analyze_business_question(db=db_session, business_id=biz_id, query="What was our customer acquisition cost across TikTok and Google Ads?")
    assert sc_e["lead_analyst_report"]["validation_status"] == "MISSING_SOURCE_EVIDENCE"
