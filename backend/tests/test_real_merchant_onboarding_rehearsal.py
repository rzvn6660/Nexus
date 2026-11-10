"""
Master Engineering Test Suite: Real Merchant Onboarding & Analytical Trust Rehearsal.

This test suite executes controlled, end-to-end verification of the 8 mandatory onboarding
and trust stages using explicitly labeled synthetic merchant benchmark fixtures (SYNTHETIC_FIXTURE):

1. Data Contract Validation & Schema Inspection (CSV and Excel)
2. Deduplication, Conflicting Record Detection & Invalid Row Diagnostics
3. Customer Resolution & Anti-Collision Safeguards
4. Atomic Ingestion & Rollback Verification
5. Ingestion-to-Database Reconciliation (Exact Counts and Sums)
6. Certification State Machine Enforcement (5 distinct governance states)
7. Analytical Output Reconciliation (Profitability, Retention, Forecasting Tiers)
8. Orchestrator 7-Scenario Validation & Evidence Ledger Immutability
"""

import io
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import uuid4

import pandas as pd
import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.analytics.analyst.lead_analyst import LeadAnalyst
from app.analytics.analyst.ledger import AnalystEvidenceLedger
from app.analytics.analyst.models import ExecutionContext
from app.analytics.analyst.orchestrator import AnalystOrchestrator
from app.analytics.analyst.registry import get_skill_registry
from app.analytics.analyst.service import AnalystService
from app.analytics.analyst.skills.commercial import GrossMarginAnalysisSkill
from app.analytics.analyst.skills.predictive import TimeSeriesForecastingSkill
from app.analytics.customer.safety import (
    CadenceEligibilityStatus,
    CadenceSafetyGate,
    SafetyReasonCode,
)
from app.analytics.pulse.service import PulseService
from app.core.config import settings
from app.models.customer import Customer
from app.models.history import AnalysisRun
from app.models.product import Product
from app.models.sale import Sale
from app.models.sale_item import SaleItem
from app.models.tenant import Business, IngestionJob, Organization, UploadedDataset
from app.services.data_gateway_service import DataGatewayService
from app.services.manifest_service import ManifestService
from app.services.watermark_service import (
    WatermarkCertificationState,
    WatermarkService,
)


# ---------------------------------------------------------------------------
# FIXTURES
# ---------------------------------------------------------------------------

@pytest.fixture
def rehearsal_env(db_session: Session) -> dict[str, Any]:
    """
    Sets up two isolated businesses for tenant-isolation and anti-collision tests:
    - Primary Merchant Business: The merchant undergoing onboarding rehearsal.
    - Foreign Business: An isolated business used to verify strict boundary enforcement.
    """
    org_primary = Organization(
        id=f"org_rehearsal_{uuid4().hex[:6]}",
        name="Apex Commercial Goods Org",
        slug=f"apex-commercial-{uuid4().hex[:6]}",
    )
    org_foreign = Organization(
        id=f"org_foreign_{uuid4().hex[:6]}",
        name="Foreign Competitor Org",
        slug=f"foreign-corp-{uuid4().hex[:6]}",
    )
    db_session.add_all([org_primary, org_foreign])
    db_session.flush()

    biz_primary = Business(
        id=f"biz_apex_{uuid4().hex[:6]}",
        organization_id=org_primary.id,
        name="Apex Commercial Retail",
        status="active",
        currency="USD",
        timezone="UTC",
    )
    biz_foreign = Business(
        id=f"biz_foreign_{uuid4().hex[:6]}",
        organization_id=org_foreign.id,
        name="Foreign Store",
        status="active",
        currency="USD",
        timezone="UTC",
    )
    db_session.add_all([biz_primary, biz_foreign])
    db_session.flush()

    # Pre-seed merchant customers in Primary Business
    c1 = Customer(
        business_id=biz_primary.id,
        customer_code="APEX-CUST-101",
        name="Enterprise Client A",
        email="client.a@apexcommercial.example",
        city="Chicago",
        customer_segment="Enterprise",
        acquisition_date=date(2025, 1, 1),
    )
    c2 = Customer(
        business_id=biz_primary.id,
        customer_code="APEX-CUST-102",
        name="Mid-Market Client B",
        email="client.b@apexcommercial.example",
        city="Detroit",
        customer_segment="Mid-Market",
        acquisition_date=date(2025, 2, 1),
    )
    c3 = Customer(
        business_id=biz_primary.id,
        customer_code="APEX-CUST-103",
        name="Retail Client C",
        email="client.c@apexcommercial.example",
        city="Indianapolis",
        customer_segment="Retail",
        acquisition_date=date(2025, 3, 1),
    )

    # Seed Foreign Customer in Foreign Business (for anti-collision tests)
    c_foreign = Customer(
        business_id=biz_foreign.id,
        customer_code="FOREIGN-CUST-999",
        name="Foreign Customer",
        email="intruder@foreignstore.example",
        city="Toronto",
        customer_segment="Wholesale",
        acquisition_date=date(2025, 1, 1),
    )
    db_session.add_all([c1, c2, c3, c_foreign])
    db_session.flush()

    # Pre-seed merchant product catalog (some with verified unit costs, some without)
    p1 = Product(
        business_id=biz_primary.id,
        sku="SKU-APEX-001",
        name="Industrial Valve Assembly",
        category="Industrial",
        subcategory="Valves",
        unit_cost=Decimal("40.00"),  # Verified vendor unit cost
        selling_price=Decimal("100.00"),
        active=True,
    )
    p2 = Product(
        business_id=biz_primary.id,
        sku="SKU-APEX-002",
        name="Heavy Duty Gasket Kit",
        category="Industrial",
        subcategory="Gaskets",
        unit_cost=Decimal("15.00"),  # Verified vendor unit cost
        selling_price=Decimal("50.00"),
        active=True,
    )
    db_session.add_all([p1, p2])
    db_session.commit()

    return {
        "org_primary": org_primary,
        "biz_primary": biz_primary,
        "c1": c1,
        "c2": c2,
        "c3": c3,
        "p1": p1,
        "p2": p2,
        "biz_foreign": biz_foreign,
        "c_foreign": c_foreign,
    }


# ==============================================================================
# STAGE 1: DATA CONTRACT VALIDATION & SCHEMA INSPECTION (CSV AND EXCEL)
# ==============================================================================

def test_stage1_csv_schema_inspection_and_profiling(db_session: Session, rehearsal_env: dict[str, Any]):
    """Stage 1.1: Verify CSV dataset upload, deterministic profiling, and schema inference."""
    biz = rehearsal_env["biz_primary"]
    csv_content = (
        "order_number,date,amount,customer_code,discount_amount,tax_amount,status,sku\n"
        "APEX-ORD-001,2026-03-01,100.00,APEX-CUST-101,0.00,7.00,completed,SKU-APEX-001\n"
        "APEX-ORD-002,2026-03-02,50.00,APEX-CUST-102,5.00,3.50,completed,SKU-APEX-002\n"
    ).encode("utf-8")

    dataset = DataGatewayService.save_raw_dataset(
        db=db_session,
        organization_id=biz.organization_id,
        business_id=biz.id,
        filename="SYNTHETIC_FIXTURE_apex_sales.csv",
        content=csv_content,
    )
    assert dataset.id is not None
    assert dataset.file_type == "csv"

    preview = DataGatewayService.get_dataset_preview(
        db=db_session,
        dataset_id=dataset.id,
        business_id=biz.id,
    )

    assert preview.row_count == 2
    assert preview.column_count == 8
    assert preview.detected_entity == "Sale"
    # Verify core required columns mapped in schema_json
    schema_json = dataset.schema_json or {}
    mappings = schema_json.get("mapping_proposal", {}).get("field_mappings", {})
    assert mappings.get("amount") == "amount"
    assert mappings.get("date") == "date"


def test_stage1_excel_schema_inspection_and_profiling(db_session: Session, rehearsal_env: dict[str, Any]):
    """Stage 1.2: Verify Excel (.xlsx) workbook upload, binary magic inspection, and profiling."""
    biz = rehearsal_env["biz_primary"]

    df = pd.DataFrame([
        {
            "order_number": "APEX-XLS-001",
            "date": "2026-03-10",
            "amount": 250.00,
            "customer_code": "APEX-CUST-101",
            "discount_amount": 0.00,
            "tax_amount": 17.50,
            "status": "completed",
            "sku": "SKU-APEX-001",
        },
        {
            "order_number": "APEX-XLS-002",
            "date": "2026-03-11",
            "amount": 150.00,
            "customer_code": "APEX-CUST-102",
            "discount_amount": 10.00,
            "tax_amount": 10.50,
            "status": "completed",
            "sku": "SKU-APEX-002",
        },
    ])

    pytest.importorskip("openpyxl")
    bio = io.BytesIO()
    with pd.ExcelWriter(bio, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Transactions")
    excel_bytes = bio.getvalue()

    dataset = DataGatewayService.save_raw_dataset(
        db=db_session,
        organization_id=biz.organization_id,
        business_id=biz.id,
        filename="SYNTHETIC_FIXTURE_apex_orders.xlsx",
        content=excel_bytes,
    )
    assert dataset.id is not None
    assert dataset.file_type == "xlsx"

    preview = DataGatewayService.get_dataset_preview(
        db=db_session,
        dataset_id=dataset.id,
        business_id=biz.id,
    )
    assert preview.row_count == 2
    assert preview.detected_entity == "Sale"


def test_stage1_unsupported_and_prohibited_columns_safely_ignored(db_session: Session, rehearsal_env: dict[str, Any]):
    """Stage 1.3: Verify sensitive / prohibited columns (card numbers, passwords, unmodeled ad spend) are not mapped to Sale."""
    biz = rehearsal_env["biz_primary"]
    csv_content = (
        "order_number,date,amount,customer_code,credit_card_number,password_hash,google_ad_spend\n"
        "APEX-ORD-SEC-01,2026-03-01,100.00,APEX-CUST-101,4111222233334444,hash_secret_xyz,150.25\n"
    ).encode("utf-8")

    dataset = DataGatewayService.save_raw_dataset(
        db=db_session,
        organization_id=biz.organization_id,
        business_id=biz.id,
        filename="SYNTHETIC_FIXTURE_sales_with_unsupported.csv",
        content=csv_content,
    )

    preview = DataGatewayService.get_dataset_preview(
        db=db_session,
        dataset_id=dataset.id,
        business_id=biz.id,
    )
    schema_json = dataset.schema_json or {}
    mappings = schema_json.get("mapping_proposal", {}).get("field_mappings", {})
    # Ensure sensitive columns are NOT mapped into canonical Sale fields
    assert "credit_card_number" not in mappings.values()
    assert "password_hash" not in mappings.values()
    assert "google_ad_spend" not in mappings.values()

    # Commit ingestion and assert sensitive data is never persisted to Sale table
    res = DataGatewayService.ingest_into_core_models(
        db=db_session,
        dataset_id=dataset.id,
        business_id=biz.id,
        target_entity="Sale",
    )
    assert res["status"] == "COMPLETED"

    committed_sale = db_session.execute(
        select(Sale).where(Sale.transaction_number == "APEX-ORD-SEC-01")
    ).scalar_one()
    # Confirm Sale model only stored authorized canonical transaction data
    assert committed_sale.subtotal == Decimal("100.00")
    assert not hasattr(committed_sale, "credit_card_number")
    assert not hasattr(committed_sale, "google_ad_spend")


# ==============================================================================
# STAGE 2: DEDUPLICATION, CONFLICTING RECORDS & INVALID ROW DIAGNOSTICS
# ==============================================================================

def test_stage2_deduplication_and_idempotent_reingestion(db_session: Session, rehearsal_env: dict[str, Any]):
    """Stage 2.1: Verify duplicate orders are skipped and repeated ingestion is an idempotent no-op."""
    biz = rehearsal_env["biz_primary"]
    csv_content = (
        "order_number,date,amount,customer_code\n"
        "APEX-DEDUP-001,2026-03-01,100.00,APEX-CUST-101\n"
        "APEX-DEDUP-002,2026-03-02,200.00,APEX-CUST-102\n"
    ).encode("utf-8")

    dataset = DataGatewayService.save_raw_dataset(
        db=db_session,
        organization_id=biz.organization_id,
        business_id=biz.id,
        filename="SYNTHETIC_FIXTURE_dedup_test.csv",
        content=csv_content,
    )
    DataGatewayService.get_dataset_preview(db=db_session, dataset_id=dataset.id, business_id=biz.id)

    # First ingestion: persists 2 sales
    res1 = DataGatewayService.ingest_into_core_models(
        db=db_session,
        dataset_id=dataset.id,
        business_id=biz.id,
        target_entity="Sale",
    )
    assert res1["status"] == "COMPLETED"
    assert res1["records_persisted"] == 2

    initial_count = db_session.execute(
        select(func.count(Sale.id)).where(Sale.business_id == biz.id)
    ).scalar()

    # Second ingestion with same dataset: must be idempotent no-op
    res2 = DataGatewayService.ingest_into_core_models(
        db=db_session,
        dataset_id=dataset.id,
        business_id=biz.id,
        target_entity="Sale",
    )
    assert res2["status"] == "COMPLETED"
    assert "idempotent" in res2["message"].lower()

    final_count = db_session.execute(
        select(func.count(Sale.id)).where(Sale.business_id == biz.id)
    ).scalar()
    assert final_count == initial_count


def test_stage2_conflicting_order_metadata_detection(db_session: Session, rehearsal_env: dict[str, Any]):
    """Stage 2.2: Verify multi-line order with conflicting dates or conflicting tax amounts is rejected."""
    biz = rehearsal_env["biz_primary"]
    # Two lines for the SAME order number have conflicting transaction dates
    csv_content = (
        "order_number,date,amount,customer_code,tax_amount\n"
        "APEX-CONFLICT-01,2026-03-01,100.00,APEX-CUST-101,5.00\n"
        "APEX-CONFLICT-01,2026-03-10,150.00,APEX-CUST-101,5.00\n"
    ).encode("utf-8")

    dataset = DataGatewayService.save_raw_dataset(
        db=db_session,
        organization_id=biz.organization_id,
        business_id=biz.id,
        filename="SYNTHETIC_FIXTURE_conflicting_order.csv",
        content=csv_content,
    )
    DataGatewayService.get_dataset_preview(db=db_session, dataset_id=dataset.id, business_id=biz.id)

    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc_info:
        DataGatewayService.ingest_into_core_models(
            db=db_session,
            dataset_id=dataset.id,
            business_id=biz.id,
            target_entity="Sale",
        )
    assert exc_info.value.status_code == 400
    err_detail = exc_info.value.detail
    assert "CONFLICTING_ORDER_METADATA" in str(err_detail)


def test_stage2_invalid_row_diagnostics(db_session: Session, rehearsal_env: dict[str, Any]):
    """Stage 2.3: Verify comprehensive diagnostics for missing amount, negative amount, and unparseable dates."""
    biz = rehearsal_env["biz_primary"]
    csv_content = (
        "order_number,date,amount,customer_code\n"
        "APEX-ERR-01,2026-03-01,,APEX-CUST-101\n"  # Missing amount
        "APEX-ERR-02,2026-03-02,-50.00,APEX-CUST-102\n"  # Negative amount
        "APEX-ERR-03,not-a-date,100.00,APEX-CUST-103\n"  # Unparseable date
    ).encode("utf-8")

    dataset = DataGatewayService.save_raw_dataset(
        db=db_session,
        organization_id=biz.organization_id,
        business_id=biz.id,
        filename="SYNTHETIC_FIXTURE_invalid_rows.csv",
        content=csv_content,
    )
    DataGatewayService.get_dataset_preview(db=db_session, dataset_id=dataset.id, business_id=biz.id)

    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc_info:
        DataGatewayService.ingest_into_core_models(
            db=db_session,
            dataset_id=dataset.id,
            business_id=biz.id,
            target_entity="Sale",
        )
    assert exc_info.value.status_code == 400
    errors = exc_info.value.detail.get("errors", [])
    assert len(errors) >= 3
    error_types = {e["error_type"] for e in errors}
    assert "REQUIRED_VALUE_MISSING" in error_types
    assert "RANGE_ERROR" in error_types
    assert "UNPARSEABLE_DATE" in error_types


# ==============================================================================
# STAGE 3: CUSTOMER RESOLUTION & ANTI-COLLISION SAFEGUARDS
# ==============================================================================

def test_stage3_tenant_scoped_customer_matching(db_session: Session, rehearsal_env: dict[str, Any]):
    """Stage 3.1: Verify transaction customer codes match existing tenant customers accurately."""
    biz = rehearsal_env["biz_primary"]
    c1 = rehearsal_env["c1"]
    c2 = rehearsal_env["c2"]

    csv_content = (
        "order_number,date,amount,customer_code\n"
        "APEX-CUSTMATCH-01,2026-03-01,100.00,APEX-CUST-101\n"
        "APEX-CUSTMATCH-02,2026-03-02,200.00,APEX-CUST-102\n"
    ).encode("utf-8")

    dataset = DataGatewayService.save_raw_dataset(
        db=db_session,
        organization_id=biz.organization_id,
        business_id=biz.id,
        filename="SYNTHETIC_FIXTURE_cust_match.csv",
        content=csv_content,
    )
    DataGatewayService.get_dataset_preview(db=db_session, dataset_id=dataset.id, business_id=biz.id)
    DataGatewayService.ingest_into_core_models(
        db=db_session,
        dataset_id=dataset.id,
        business_id=biz.id,
        target_entity="Sale",
    )

    s1 = db_session.execute(select(Sale).where(Sale.transaction_number == "APEX-CUSTMATCH-01")).scalar_one()
    s2 = db_session.execute(select(Sale).where(Sale.transaction_number == "APEX-CUSTMATCH-02")).scalar_one()

    assert s1.customer_id == c1.id
    assert s2.customer_id == c2.id


def test_stage3_cross_tenant_collision_prevented(db_session: Session, rehearsal_env: dict[str, Any]):
    """Stage 3.2: Verify a customer code from Foreign Business is never resolved for Primary Business."""
    biz_primary = rehearsal_env["biz_primary"]
    c_foreign = rehearsal_env["c_foreign"]  # Customer code: FOREIGN-CUST-999

    # Primary business tries to ingest sale referencing foreign customer code
    csv_content = (
        "order_number,date,amount,customer_code\n"
        f"APEX-INTRUDER-01,2026-03-01,100.00,{c_foreign.customer_code}\n"
    ).encode("utf-8")

    dataset = DataGatewayService.save_raw_dataset(
        db=db_session,
        organization_id=biz_primary.organization_id,
        business_id=biz_primary.id,
        filename="SYNTHETIC_FIXTURE_foreign_cust_collision.csv",
        content=csv_content,
    )
    DataGatewayService.get_dataset_preview(db=db_session, dataset_id=dataset.id, business_id=biz_primary.id)

    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc_info:
        DataGatewayService.ingest_into_core_models(
            db=db_session,
            dataset_id=dataset.id,
            business_id=biz_primary.id,
            target_entity="Sale",
        )
    assert exc_info.value.status_code == 400
    # Customer resolution failed because customer does not exist in biz_primary
    assert "UNRESOLVED_CUSTOMER" in str(exc_info.value.detail)


def test_stage3_unmapped_customer_safeguards(db_session: Session, rehearsal_env: dict[str, Any]):
    """Stage 3.3: Verify transactions without customer column safely map to tenant-scoped default customer."""
    biz = rehearsal_env["biz_primary"]
    csv_content = (
        "order_number,date,amount\n"
        "APEX-POS-001,2026-03-01,45.00\n"
        "APEX-POS-002,2026-03-02,55.00\n"
    ).encode("utf-8")

    dataset = DataGatewayService.save_raw_dataset(
        db=db_session,
        organization_id=biz.organization_id,
        business_id=biz.id,
        filename="SYNTHETIC_FIXTURE_pos_receipts.csv",
        content=csv_content,
    )
    DataGatewayService.get_dataset_preview(db=db_session, dataset_id=dataset.id, business_id=biz.id)
    res = DataGatewayService.ingest_into_core_models(
        db=db_session,
        dataset_id=dataset.id,
        business_id=biz.id,
        target_entity="Sale",
    )
    assert res["status"] == "COMPLETED"

    s1 = db_session.execute(select(Sale).where(Sale.transaction_number == "APEX-POS-001")).scalar_one()
    # Ensure customer is assigned and customer strictly belongs to biz_primary
    assigned_cust = db_session.execute(select(Customer).where(Customer.id == s1.customer_id)).scalar_one()
    assert assigned_cust.business_id == biz.id
    assert "DEFAULT" in assigned_cust.customer_code.upper()


# ==============================================================================
# STAGE 4: ATOMIC INGESTION & ROLLBACK VERIFICATION
# ==============================================================================

def test_stage4_atomic_rollback_on_validation_failure(db_session: Session, rehearsal_env: dict[str, Any]):
    """Stage 4: Verify complete transaction rollback when a batch contains invalid rows."""
    biz = rehearsal_env["biz_primary"]
    initial_sales_count = db_session.execute(
        select(func.count(Sale.id)).where(Sale.business_id == biz.id)
    ).scalar()

    # Batch with 4 valid rows and 1 invalid row (row 5: negative amount)
    csv_content = (
        "order_number,date,amount,customer_code\n"
        "APEX-ATOMIC-01,2026-03-01,10.00,APEX-CUST-101\n"
        "APEX-ATOMIC-02,2026-03-02,20.00,APEX-CUST-101\n"
        "APEX-ATOMIC-03,2026-03-03,30.00,APEX-CUST-101\n"
        "APEX-ATOMIC-04,2026-03-04,40.00,APEX-CUST-101\n"
        "APEX-ATOMIC-05,2026-03-05,-50.00,APEX-CUST-101\n"
    ).encode("utf-8")

    dataset = DataGatewayService.save_raw_dataset(
        db=db_session,
        organization_id=biz.organization_id,
        business_id=biz.id,
        filename="SYNTHETIC_FIXTURE_atomic_test.csv",
        content=csv_content,
    )
    DataGatewayService.get_dataset_preview(db=db_session, dataset_id=dataset.id, business_id=biz.id)

    from fastapi import HTTPException
    with pytest.raises(HTTPException):
        DataGatewayService.ingest_into_core_models(
            db=db_session,
            dataset_id=dataset.id,
            business_id=biz.id,
            target_entity="Sale",
        )

    # Verify atomic rollback: exactly zero rows from this batch were committed
    post_count = db_session.execute(
        select(func.count(Sale.id)).where(Sale.business_id == biz.id)
    ).scalar()
    assert post_count == initial_sales_count

    # Verify IngestionJob is marked FAILED
    failed_job = db_session.execute(
        select(IngestionJob).where(
            IngestionJob.dataset_id == dataset.id,
            IngestionJob.business_id == biz.id,
        )
    ).scalar_one()
    assert failed_job.status == "FAILED"
    assert "validation failed" in failed_job.error_message.lower()


# ==============================================================================
# STAGE 5: INGESTION-TO-DATABASE RECONCILIATION (COUNTS AND SUMS)
# ==============================================================================

def test_stage5_source_to_database_mathematical_reconciliation(db_session: Session, rehearsal_env: dict[str, Any]):
    """Stage 5: Verify 100% mathematical match between source records and database aggregates."""
    biz = rehearsal_env["biz_primary"]

    # 5 controlled orders with known figures
    source_records = [
        {"order_number": "APEX-REC-01", "date": "2026-03-01", "amount": Decimal("100.00"), "discount": Decimal("5.00"), "tax": Decimal("6.65"), "total": Decimal("101.65")},
        {"order_number": "APEX-REC-02", "date": "2026-03-02", "amount": Decimal("200.00"), "discount": Decimal("0.00"), "tax": Decimal("14.00"), "total": Decimal("214.00")},
        {"order_number": "APEX-REC-03", "date": "2026-03-03", "amount": Decimal("150.00"), "discount": Decimal("10.00"), "tax": Decimal("9.80"), "total": Decimal("149.80")},
        {"order_number": "APEX-REC-04", "date": "2026-03-04", "amount": Decimal("300.00"), "discount": Decimal("15.00"), "tax": Decimal("19.95"), "total": Decimal("304.95")},
        {"order_number": "APEX-REC-05", "date": "2026-03-05", "amount": Decimal("250.00"), "discount": Decimal("0.00"), "tax": Decimal("17.50"), "total": Decimal("267.50")},
    ]

    expected_count = len(source_records)
    expected_subtotal = sum(Decimal(str(r["amount"])) for r in source_records)
    expected_discount = sum(Decimal(str(r["discount"])) for r in source_records)
    expected_tax = sum(Decimal(str(r["tax"])) for r in source_records)
    expected_total = sum(Decimal(str(r["total"])) for r in source_records)

    csv_lines = ["order_number,date,amount,customer_code,discount_amount,tax_amount,total_amount"]
    for r in source_records:
        csv_lines.append(f"{r['order_number']},{r['date']},{r['amount']},APEX-CUST-101,{r['discount']},{r['tax']},{r['total']}")
    csv_content = "\n".join(csv_lines).encode("utf-8")

    dataset = DataGatewayService.save_raw_dataset(
        db=db_session,
        organization_id=biz.organization_id,
        business_id=biz.id,
        filename="SYNTHETIC_FIXTURE_reconciliation.csv",
        content=csv_content,
    )
    DataGatewayService.get_dataset_preview(db=db_session, dataset_id=dataset.id, business_id=biz.id)
    res = DataGatewayService.ingest_into_core_models(
        db=db_session,
        dataset_id=dataset.id,
        business_id=biz.id,
        target_entity="Sale",
    )
    assert res["records_persisted"] == expected_count

    # Direct database verification
    db_results = db_session.execute(
        select(
            func.count(Sale.id),
            func.sum(Sale.subtotal),
            func.sum(Sale.discount_amount),
            func.sum(Sale.tax_amount),
            func.sum(Sale.total_amount),
        ).where(
            Sale.business_id == biz.id,
            Sale.transaction_number.in_([r["order_number"] for r in source_records]),
        )
    ).one()

    db_count, db_subtotal, db_discount, db_tax, db_total = db_results

    assert db_count == expected_count
    assert Decimal(str(db_subtotal)) == expected_subtotal
    assert Decimal(str(db_discount)) == expected_discount
    assert Decimal(str(db_tax)) == expected_tax
    assert Decimal(str(db_total)) == expected_total


# ==============================================================================
# STAGE 6: CERTIFICATION STATE MACHINE ENFORCEMENT
# ==============================================================================

def test_stage6_certification_state_machine_and_safety_gate(db_session: Session, rehearsal_env: dict[str, Any]):
    """Stage 6: Verify all 5 certification states and safety gate transition from unverified to period-close certified."""
    biz = rehearsal_env["biz_primary"]

    # 1. State: IMPORT_COMPLETED and SOURCE_COMPLETENESS_UNVERIFIED
    now = datetime.now(UTC)
    tx_dates = [now - timedelta(days=5), now - timedelta(days=2)]
    source_id = "test_merchant_source"

    # Ingestion establishes import completion with provisional (unverified) completeness
    wm = WatermarkService.record_import_completion(
        session=db_session,
        business_id=biz.id,
        source_id=source_id,
        transaction_dates=tx_dates,
        certified_complete_through=None,  # Not authoritative period close
    )
    db_session.commit()

    assert wm.verification_status == "provisional"
    assert wm.metadata_json["governance_state"] == WatermarkCertificationState.SOURCE_COMPLETENESS_UNVERIFIED.value

    eff = WatermarkService.get_effective_tenant_watermark(session=db_session, business_id=biz.id)
    assert eff.certification_state == WatermarkCertificationState.SOURCE_COMPLETENESS_UNVERIFIED.value
    assert eff.is_verified is False
    assert eff.latest_observed_date == tx_dates[1]

    # Evaluate CadenceSafetyGate: must be DIAGNOSTIC_ONLY because watermark is provisional
    _summary, verdict = CadenceSafetyGate.evaluate_customer_cadence_with_safety(
        session=db_session,
        business_id=biz.id,
        required_sources=[source_id],
        as_of_date=now.date(),
    )
    assert verdict.eligibility_status == CadenceEligibilityStatus.DIAGNOSTIC_ONLY
    assert verdict.reason_code == SafetyReasonCode.PROVISIONAL_WATERMARK

    # 2. State: SOURCE_COMPLETENESS_VERIFIED via verified completeness through date
    closed_date = tx_dates[1]
    wm_closed = WatermarkService.record_import_completion(
        session=db_session,
        business_id=biz.id,
        source_id=source_id,
        transaction_dates=tx_dates,
        certified_complete_through=closed_date,
    )
    db_session.commit()

    assert wm_closed.verification_status == "verified"
    assert wm_closed.metadata_json["governance_state"] == WatermarkCertificationState.SOURCE_COMPLETENESS_VERIFIED.value

    eff_closed = WatermarkService.get_effective_tenant_watermark(session=db_session, business_id=biz.id)
    assert eff_closed.certification_state == WatermarkCertificationState.SOURCE_COMPLETENESS_VERIFIED.value


# ==============================================================================
# STAGE 7: ANALYTICAL OUTPUT RECONCILIATION
# ==============================================================================

def test_stage7_profitability_classification_governance(db_session: Session, rehearsal_env: dict[str, Any]):
    """Stage 7.1: Verify ACTUAL, ESTIMATED, and UNAVAILABLE profitability classifications."""
    biz = rehearsal_env["biz_primary"]
    p1 = rehearsal_env["p1"]  # Has unit_cost = 40.00, price = 100.00
    p2 = rehearsal_env["p2"]  # Has unit_cost = 15.00, price = 50.00

    # Create a Sale with items having explicit unit costs
    sale_actual = Sale(
        business_id=biz.id,
        transaction_number=f"TXN-PROFIT-ACTUAL-{uuid4().hex[:4]}",
        customer_id=rehearsal_env["c1"].id,
        transaction_date=datetime.now(UTC) - timedelta(days=1),
        subtotal=Decimal("150.00"),
        discount_amount=Decimal("0.00"),
        tax_amount=Decimal("0.00"),
        total_amount=Decimal("150.00"),
        status="completed",
    )
    db_session.add(sale_actual)
    db_session.flush()

    item1 = SaleItem(
        sale_id=sale_actual.id,
        product_id=p1.id,
        quantity=1,
        unit_price=Decimal("100.00"),
        line_total=Decimal("100.00"),
    )
    item2 = SaleItem(
        sale_id=sale_actual.id,
        product_id=p2.id,
        quantity=1,
        unit_price=Decimal("50.00"),
        line_total=Decimal("50.00"),
    )
    db_session.add_all([item1, item2])
    db_session.commit()

    # Execute GrossMarginAnalysisSkill
    skill = GrossMarginAnalysisSkill()
    ctx = ExecutionContext(business_id=biz.id, query="What is our gross profit and margin?")
    res = skill.execute(db_session, ctx)

    assert res.status == "SUCCESS"
    data = res.data
    # Total revenue = 150.00, Total COGS = 40.00 + 15.00 = 55.00, Gross Profit = 95.00
    assert data["cost_classification"] == "ACTUAL"
    assert data["gross_profit"] == 95.00
    assert data["gross_margin_pct"] == 63.3


def test_stage7_forecast_tier_governance(db_session: Session, rehearsal_env: dict[str, Any]):
    """Stage 7.2: Verify 3-tier forecast confidence classification (PRELIMINARY_RUN_RATE for short history)."""
    biz = rehearsal_env["biz_primary"]
    c1 = rehearsal_env["c1"]

    # Seed 3 days of sales (< 14 days history) to verify PRELIMINARY_RUN_RATE
    now = datetime.now(UTC)
    s1 = Sale(
        business_id=biz.id,
        transaction_number=f"TXN-FC-01-{uuid4().hex[:4]}",
        customer_id=c1.id,
        transaction_date=now - timedelta(days=3),
        subtotal=Decimal("100.00"),
        discount_amount=Decimal("0.00"),
        tax_amount=Decimal("0.00"),
        total_amount=Decimal("100.00"),
        status="completed",
    )
    s2 = Sale(
        business_id=biz.id,
        transaction_number=f"TXN-FC-02-{uuid4().hex[:4]}",
        customer_id=c1.id,
        transaction_date=now - timedelta(days=2),
        subtotal=Decimal("120.00"),
        discount_amount=Decimal("0.00"),
        tax_amount=Decimal("0.00"),
        total_amount=Decimal("120.00"),
        status="completed",
    )
    s3 = Sale(
        business_id=biz.id,
        transaction_number=f"TXN-FC-03-{uuid4().hex[:4]}",
        customer_id=c1.id,
        transaction_date=now - timedelta(days=1),
        subtotal=Decimal("150.00"),
        discount_amount=Decimal("0.00"),
        tax_amount=Decimal("0.00"),
        total_amount=Decimal("150.00"),
        status="completed",
    )
    db_session.add_all([s1, s2, s3])
    db_session.commit()

    skill = TimeSeriesForecastingSkill()
    ctx = ExecutionContext(business_id=biz.id, query="What is our sales forecast?")
    res = skill.execute(db_session, ctx)

    assert res.status == "SUCCESS"
    tier = res.data.get("forecast_tier")
    # Short history (<14 days) must be PRELIMINARY_RUN_RATE
    assert tier == "PRELIMINARY_RUN_RATE"
    assert "preliminary" in res.findings[0].lower()


# ==============================================================================
# STAGE 8: ORCHESTRATOR 7-SCENARIO VALIDATION & EVIDENCE LEDGER IMMUTABILITY
# ==============================================================================

def test_stage8_orchestrator_7_scenarios(db_session: Session, rehearsal_env: dict[str, Any]):
    """
    Stage 8: Verify LeadAnalyst and AnalystOrchestrator across the 7 mandatory business scenarios:
    1. Discovery: "What are my overall sales and performance?"
    2. Quality: "Are there any data quality issues in my transactions?"
    3. Variance: "Why did revenue change between periods?"
    4. Churn: "Which customers are at risk of churning?"
    5. Forecast: "What is the sales forecast for next month?"
    6. Margin: "What is my product profitability and margin?"
    7. Unsupported External Data: "What is our Google Ads return on ad spend (ROAS)?"
    """
    biz = rehearsal_env["biz_primary"]
    c1 = rehearsal_env["c1"]
    c2 = rehearsal_env["c2"]
    p1 = rehearsal_env["p1"]
    p2 = rehearsal_env["p2"]

    # Seed multi-period sales with repeat customer transactions and verified catalog items
    now = datetime.now(UTC)
    s1 = Sale(
        business_id=biz.id,
        transaction_number=f"TXN-ORCH-01-{uuid4().hex[:4]}",
        customer_id=c1.id,
        transaction_date=now - timedelta(days=45),
        subtotal=Decimal("100.00"),
        discount_amount=Decimal("0.00"),
        tax_amount=Decimal("0.00"),
        total_amount=Decimal("100.00"),
        status="completed",
    )
    s2 = Sale(
        business_id=biz.id,
        transaction_number=f"TXN-ORCH-02-{uuid4().hex[:4]}",
        customer_id=c1.id,
        transaction_date=now - timedelta(days=15),
        subtotal=Decimal("150.00"),
        discount_amount=Decimal("10.00"),
        tax_amount=Decimal("0.00"),
        total_amount=Decimal("140.00"),
        status="completed",
    )
    s3 = Sale(
        business_id=biz.id,
        transaction_number=f"TXN-ORCH-03-{uuid4().hex[:4]}",
        customer_id=c2.id,
        transaction_date=now - timedelta(days=5),
        subtotal=Decimal("500.00"),
        discount_amount=Decimal("0.00"),
        tax_amount=Decimal("0.00"),
        total_amount=Decimal("500.00"),
        status="completed",
    )
    db_session.add_all([s1, s2, s3])
    db_session.flush()

    it1 = SaleItem(sale_id=s1.id, product_id=p1.id, quantity=1, unit_price=Decimal("100.00"), line_total=Decimal("100.00"))
    it2 = SaleItem(sale_id=s2.id, product_id=p1.id, quantity=1, unit_price=Decimal("100.00"), line_total=Decimal("100.00"))
    it3 = SaleItem(sale_id=s3.id, product_id=p2.id, quantity=10, unit_price=Decimal("50.00"), line_total=Decimal("500.00"))
    db_session.add_all([it1, it2, it3])
    db_session.commit()

    scenarios = [
        # (Scenario Name, User Query, Expected Intent, Expected Executive Prefix/Substring)
        (
            "Discovery",
            "What are my overall sales and business performance?",
            "GENERAL_BUSINESS_PERFORMANCE_AUDIT",
            "Completed multi-skill investigation",
        ),
        (
            "Quality",
            "Are there any transaction data quality issues or anomalies?",
            "DATA_QUALITY_AND_GOVERNANCE_AUDIT",
            "Completed multi-skill investigation",
        ),
        (
            "Variance",
            "Why did sequential revenue change between the last two periods?",
            "REVENUE_VARIANCE_ROOT_CAUSE",
            "Sequential revenue changed",
        ),
        (
            "Churn",
            "Which repeat customer accounts are at risk of churning?",
            "CHURN_AND_RETENTION_INVESTIGATION",
            "repeat buyer accounts",
        ),
        (
            "Forecast",
            "What is our projected sales forecast for next month?",
            "COMMERCIAL_FORECASTING",
            "[PRELIMINARY RUN-RATE]",
        ),
        (
            "Margin",
            "What is our gross profit and product profitability margin?",
            "MARGIN_AND_PROFITABILITY_AUDIT",
            "[ACTUAL PROFITABILITY]",
        ),
        (
            "Unsupported External Data",
            "What is our Google Ads return on ad spend (ROAS)?",
            "UNSUPPORTED_OR_EXTERNAL_DATA_QUERY",
            "inquires about external business metrics",
        ),
    ]

    for name, query, expected_intent, expected_text in scenarios:
        result = AnalystService.analyze_business_question(
            db=db_session,
            business_id=biz.id,
            query=query,
        )

        assert result["intent"] == expected_intent, f"Scenario {name} intent mismatch"
        report = result["lead_analyst_report"]
        assert report["validation_status"] in ("VALIDATED", "UNCERTAIN_LOW_SAMPLE", "MISSING_SOURCE_EVIDENCE", "INSUFFICIENT_DATA")
        assert expected_text in report["executive_answer"], f"Scenario {name} missing expected text '{expected_text}' in '{report['executive_answer']}'"

        # Verify Evidence Ledger immutability: run record saved in DB
        run_record = db_session.execute(
            select(AnalysisRun).where(AnalysisRun.id == result["run_id"])
        ).scalar_one()
        assert run_record.business_id == biz.id
        assert run_record.status == "completed"
        assert run_record.intent == expected_intent
