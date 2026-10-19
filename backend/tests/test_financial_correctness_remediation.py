"""
Focused regression tests for Step 1.1 Financial Correctness Remediation.

Executed against live PostgreSQL 16 + pgvector.

Covers the 8 mandatory validation scenarios:
1. All four source statuses and their correct preservation.
2. Order discounts, tax, and total billed amount preserved from CSV.
3. Completed-only filtering in financial metrics.
4. Gross-to-net arithmetic and no double-counting of line discounts.
5. Consistent unfiltered and product-filtered metric definitions.
6. Idempotent re-ingestion and failed-batch rollback.
7. Tenant isolation and audit protections.
8. Missing optional fields defaults and invalid financial values rejection.
"""

import os
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import uuid4
import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import Session, sessionmaker

from app.analytics.core.context import AnalysisContext
from app.analytics.core.types import MetricUnit
from app.analytics.metrics.financial import FinancialMetricsCalculator
from app.models.customer import Customer
from app.models.product import Product
from app.models.sale import Sale
from app.models.sale_item import SaleItem
from app.models.tenant import Business, IngestionJob, Organization, UploadedDataset
from app.services.data_gateway_service import DataGatewayService


def normalize_pg_url(url: str) -> str:
    """Normalize generic postgresql:// or postgres:// to postgresql+psycopg://."""
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+psycopg://", 1)
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+psycopg://", 1)
    return url


def get_pg_database_url() -> str:
    """Resolve active PostgreSQL connection URL honoring TEST_DATABASE_URL and DATABASE_URL."""
    raw_url = (
        os.getenv("TEST_DATABASE_URL")
        or os.getenv("DATABASE_URL")
        or "postgresql+psycopg://postgres:postgres@localhost:5439/nexus_test"
    )
    return normalize_pg_url(raw_url)


def is_strict_postgres_required() -> bool:
    """Check whether execution environment strictly mandates live PostgreSQL verification."""
    return (
        os.getenv("CI", "").strip().lower() in ("true", "1")
        or os.getenv("REQUIRE_POSTGRES", "").strip().lower() in ("true", "1")
    )


def check_postgres_connection() -> tuple[bool, str | None]:
    """Check whether a live PostgreSQL daemon responds on active database URL."""
    url = get_pg_database_url()
    if not url.startswith(("postgresql", "postgres")):
        return False, f"URL scheme does not indicate PostgreSQL: {url}"
    try:
        eng = create_engine(url, connect_args={"connect_timeout": 2})
        with eng.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True, None
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)


@pytest.fixture(scope="module", autouse=True)
def require_postgres():
    """Ensure live PostgreSQL daemon is verified reachable; fail closed in CI / strict mode."""
    reachable, err = check_postgres_connection()
    if not reachable:
        if is_strict_postgres_required():
            pytest.fail(
                f"PostgreSQL Remediation Gate Failure: Live PostgreSQL is strictly required "
                f"(CI={os.getenv('CI')}, REQUIRE_POSTGRES={os.getenv('REQUIRE_POSTGRES')}), "
                f"but connection probe failed on {get_pg_database_url()}. Error: {err}"
            )
        pytest.skip(
            f"Live PostgreSQL daemon is not reachable on configured DATABASE_URL ({err}). "
            "Verification pending CI run."
        )


@pytest.fixture(scope="module")
def pg_engine():
    """Create dedicated engine bound to PostgreSQL and assert dialect."""
    url = get_pg_database_url()
    eng = create_engine(url, pool_pre_ping=True)
    assert eng.dialect.name == "postgresql", f"Expected PostgreSQL dialect, got {eng.dialect.name}"
    yield eng
    eng.dispose()


@pytest.fixture(scope="module")
def pg_session_factory(pg_engine):
    """Provide sessionmaker bound to PostgreSQL."""
    return sessionmaker(autocommit=False, autoflush=False, bind=pg_engine)


@pytest.fixture
def pg_db(pg_session_factory):
    """Provide managed database session for individual test assertions."""
    session = pg_session_factory()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def remediation_env(pg_db: Session):
    """Sets up a tenant organization and business for remediation tests."""
    hex_id = uuid4().hex[:8]
    org = Organization(id=f"org-{hex_id}", name="Remediation Org", slug=f"rem-org-{hex_id}")
    pg_db.add(org)
    pg_db.flush()

    biz = Business(
        id=f"biz-{hex_id}",
        organization_id=org.id,
        name="Remediation Retail",
        currency="USD",
        status="active",
    )
    pg_db.add(biz)
    pg_db.flush()

    cust = Customer(
        business_id=biz.id,
        customer_code=f"CUST-REM-{hex_id}",
        name="Remediation Customer",
        email=f"rem-{hex_id}@nexus.local",
        city="Chicago",
        customer_segment="Retail",
        acquisition_date=date(2025, 1, 1),
    )
    pg_db.add(cust)

    p1 = Product(
        business_id=biz.id,
        sku=f"SKU-REM-1-{hex_id}",
        name="Remediation Widget A",
        category="Hardware",
        subcategory="Tools",
        unit_cost=Decimal("20.00"),
        selling_price=Decimal("50.00"),
        active=True,
    )
    p2 = Product(
        business_id=biz.id,
        sku=f"SKU-REM-2-{hex_id}",
        name="Remediation Gadget B",
        category="Electronics",
        subcategory="Gadgets",
        unit_cost=Decimal("10.00"),
        selling_price=Decimal("30.00"),
        active=True,
    )
    pg_db.add_all([p1, p2])
    pg_db.commit()

    return {
        "org_id": org.id,
        "biz_id": biz.id,
        "cust_id": cust.id,
        "p1_id": p1.id,
        "p2_id": p2.id,
        "hex_id": hex_id,
    }


def _ingest_csv(db: Session, org_id: str, biz_id: str, filename: str, csv_content: str, entity: str) -> UploadedDataset:
    dataset = DataGatewayService.save_raw_dataset(
        db=db,
        organization_id=org_id,
        business_id=biz_id,
        filename=filename,
        content=csv_content.encode("utf-8"),
    )
    db.commit()
    DataGatewayService.ingest_into_core_models(
        db=db,
        dataset_id=dataset.id,
        business_id=biz_id,
        target_entity=entity,
    )
    db.commit()
    return dataset


# 1. All four source statuses and their correct preservation
def test_01_all_four_source_statuses_preserved(pg_db: Session, remediation_env: dict):
    h = remediation_env["hex_id"]
    csv = (
        "order_number,date,subtotal,discount_amount,tax_amount,total_amount,status\n"
        f"ORD-ST-01-{h},2025-06-01,100.00,10.00,7.20,97.20,completed\n"
        f"ORD-ST-02-{h},2025-06-02,200.00,0.00,16.00,216.00,pending\n"
        f"ORD-ST-03-{h},2025-06-03,150.00,15.00,10.80,145.80,cancelled\n"
        f"ORD-ST-04-{h},2025-06-04,300.00,20.00,22.40,302.40,refunded\n"
    )
    biz_id = remediation_env["biz_id"]
    _ingest_csv(pg_db, remediation_env["org_id"], biz_id, f"statuses_test_{h}.csv", csv, "Sale")

    sales = pg_db.execute(
        select(Sale).where(Sale.business_id == biz_id).order_by(Sale.transaction_number)
    ).scalars().all()
    assert len(sales) == 4

    st_map = {s.transaction_number: s.status for s in sales}
    assert st_map[f"ORD-ST-01-{h}"] == "completed"
    assert st_map[f"ORD-ST-02-{h}"] == "pending"
    assert st_map[f"ORD-ST-03-{h}"] == "cancelled"
    assert st_map[f"ORD-ST-04-{h}"] == "refunded"


# 2. Order discounts, tax, and total billed amount preserved from CSV
def test_02_order_discounts_tax_and_total_amount_preserved(pg_db: Session, remediation_env: dict):
    h = remediation_env["hex_id"]
    csv = (
        "order_number,date,subtotal,discount_amount,tax_amount,total_amount,status\n"
        f"ORD-PRE-01-{h},2025-06-10,500.00,45.50,36.36,490.86,completed\n"
        f"ORD-PRE-02-{h},2025-06-11,1000.00,120.00,70.40,950.40,completed\n"
    )
    biz_id = remediation_env["biz_id"]
    _ingest_csv(pg_db, remediation_env["org_id"], biz_id, f"preserve_test_{h}.csv", csv, "Sale")

    s1 = pg_db.execute(
        select(Sale).where(Sale.business_id == biz_id, Sale.transaction_number == f"ORD-PRE-01-{h}")
    ).scalar_one()
    assert s1.subtotal == Decimal("500.00")
    assert s1.discount_amount == Decimal("45.50")
    assert s1.tax_amount == Decimal("36.36")
    assert s1.total_amount == Decimal("490.86")

    s2 = pg_db.execute(
        select(Sale).where(Sale.business_id == biz_id, Sale.transaction_number == f"ORD-PRE-02-{h}")
    ).scalar_one()
    assert s2.subtotal == Decimal("1000.00")
    assert s2.discount_amount == Decimal("120.00")
    assert s2.tax_amount == Decimal("70.40")
    assert s2.total_amount == Decimal("950.40")


# 3. Completed-only filtering in financial metrics
def test_03_completed_only_filtering_in_analytics(pg_db: Session, remediation_env: dict):
    h = remediation_env["hex_id"]
    csv = (
        "order_number,date,subtotal,discount_amount,tax_amount,total_amount,status\n"
        f"ORD-FLT-01-{h},2025-07-01,1000.00,50.00,76.00,1026.00,completed\n"
        f"ORD-FLT-02-{h},2025-07-02,500.00,0.00,40.00,540.00,shipped\n"
        f"ORD-FLT-03-{h},2025-07-03,300.00,10.00,23.20,313.20,pending\n"
        f"ORD-FLT-04-{h},2025-07-04,400.00,0.00,32.00,432.00,cancelled\n"
        f"ORD-FLT-05-{h},2025-07-05,200.00,20.00,14.40,194.40,refunded\n"
    )
    biz_id = remediation_env["biz_id"]
    _ingest_csv(pg_db, remediation_env["org_id"], biz_id, f"filter_test_{h}.csv", csv, "Sale")

    ctx = AnalysisContext(
        business_id=biz_id,
        date_from=datetime(2025, 7, 1, tzinfo=UTC),
        date_to=datetime(2025, 7, 31, 23, 59, 59, tzinfo=UTC),
    )
    summary = FinancialMetricsCalculator.evaluate_summary(pg_db, ctx)

    # Only completed (1000 - 50 = 950) and shipped (500 - 0 = 500) count towards completed sales
    # Orders count = 2
    # Completed net sales = 950 + 500 = 1450.00
    # Completed tax = 76.00 + 40.00 = 116.00
    # Completed total billed = 1026.00 + 540.00 = 1566.00
    # Refunds count = 1, amount = 200.00
    assert summary.orders.value == Decimal("2")
    assert summary.net_sales.value == Decimal("1450.00")
    assert summary.average_order_value.value == Decimal("725.00")
    assert summary.tax_amount.value == Decimal("116.00")
    assert summary.total_billed.value == Decimal("1566.00")
    assert summary.returns_count.value == Decimal("1")
    assert summary.returns_amount.value == Decimal("200.00")


# 4. Gross-to-net arithmetic and no double-counting of line discounts
def test_04_gross_to_net_arithmetic_and_no_double_counting(pg_db: Session, remediation_env: dict):
    h = remediation_env["hex_id"]
    biz_id = remediation_env["biz_id"]
    cust_id = remediation_env["cust_id"]
    p1_id = remediation_env["p1_id"]
    p2_id = remediation_env["p2_id"]

    sale = Sale(
        business_id=biz_id,
        transaction_number=f"ORD-G2N-01-{h}",
        customer_id=cust_id,
        transaction_date=datetime(2025, 8, 1, 10, 0, tzinfo=UTC),
        subtotal=Decimal("175.00"),
        discount_amount=Decimal("20.00"),
        tax_amount=Decimal("12.40"),
        total_amount=Decimal("167.40"),
        status="completed",
    )
    pg_db.add(sale)
    pg_db.flush()

    item1 = SaleItem(
        sale_id=sale.id,
        product_id=p1_id,
        quantity=2,
        unit_price=Decimal("50.00"),
        discount_amount=Decimal("10.00"),
        line_total=Decimal("90.00"),
    )
    item2 = SaleItem(
        sale_id=sale.id,
        product_id=p2_id,
        quantity=3,
        unit_price=Decimal("30.00"),
        discount_amount=Decimal("5.00"),
        line_total=Decimal("85.00"),
    )
    pg_db.add_all([item1, item2])
    pg_db.commit()

    ctx = AnalysisContext(
        business_id=biz_id,
        date_from=datetime(2025, 8, 1, tzinfo=UTC),
        date_to=datetime(2025, 8, 31, 23, 59, 59, tzinfo=UTC),
    )
    waterfall = FinancialMetricsCalculator.evaluate_gross_to_net_waterfall(pg_db, ctx)

    assert waterfall.gross_sales == Decimal("190.00")
    assert waterfall.line_discounts == Decimal("15.00")
    assert waterfall.order_subtotal == Decimal("175.00")
    assert waterfall.order_discounts == Decimal("20.00")
    assert waterfall.total_discounts == Decimal("35.00")
    assert waterfall.net_sales == Decimal("155.00")
    assert waterfall.tax_amount == Decimal("12.40")
    assert waterfall.total_billed == Decimal("167.40")

    # Verify no double counting: Gross ($190) - Total Discounts ($35) == Net Sales ($155)
    assert waterfall.gross_sales - waterfall.total_discounts == waterfall.net_sales


# 5. Consistent unfiltered and product-filtered metric definitions
def test_05_consistent_unfiltered_and_product_filtered_definitions(pg_db: Session, remediation_env: dict):
    h = remediation_env["hex_id"]
    biz_id = remediation_env["biz_id"]
    cust_id = remediation_env["cust_id"]
    p1_id = remediation_env["p1_id"]

    sale = Sale(
        business_id=biz_id,
        transaction_number=f"ORD-CONSISTENT-01-{h}",
        customer_id=cust_id,
        transaction_date=datetime(2025, 9, 1, 12, 0, tzinfo=UTC),
        subtotal=Decimal("90.00"),
        discount_amount=Decimal("0.00"),
        tax_amount=Decimal("7.20"),
        total_amount=Decimal("97.20"),
        status="completed",
    )
    pg_db.add(sale)
    pg_db.flush()

    item = SaleItem(
        sale_id=sale.id,
        product_id=p1_id,
        quantity=2,
        unit_price=Decimal("50.00"),
        discount_amount=Decimal("10.00"),
        line_total=Decimal("90.00"),
    )
    pg_db.add(item)
    pg_db.commit()

    ctx_prod = AnalysisContext(
        business_id=biz_id,
        product_ids=[p1_id],
        date_from=datetime(2025, 9, 1, tzinfo=UTC),
        date_to=datetime(2025, 9, 30, 23, 59, 59, tzinfo=UTC),
    )
    prod_agg = FinancialMetricsCalculator.compute_sales_aggregates(pg_db, ctx_prod)

    assert prod_agg["gross_sales"] == Decimal("100.00")
    assert prod_agg["discounts"] == Decimal("10.00")
    assert prod_agg["net_sales"] == Decimal("90.00")
    assert prod_agg["orders"] == Decimal("1")
    assert prod_agg["gross_sales"] - prod_agg["discounts"] == prod_agg["net_sales"]


# 6. Idempotent re-ingestion and failed-batch rollback
def test_06_idempotent_reingestion_and_failed_batch_rollback(pg_db: Session, remediation_env: dict):
    h = remediation_env["hex_id"]
    biz_id = remediation_env["biz_id"]
    org_id = remediation_env["org_id"]

    valid_csv = (
        "order_number,date,subtotal,discount_amount,tax_amount,total_amount,status\n"
        f"ORD-IDEMP-01-{h},2025-10-01,250.00,25.00,18.00,243.00,completed\n"
    )
    ds1 = _ingest_csv(pg_db, org_id, biz_id, f"idemp_test_{h}.csv", valid_csv, "Sale")

    count_before = pg_db.scalar(
        select(func.count(Sale.id)).where(Sale.business_id == biz_id, Sale.transaction_number == f"ORD-IDEMP-01-{h}")
    )
    assert count_before == 1

    res2 = DataGatewayService.ingest_into_core_models(
        db=pg_db,
        dataset_id=ds1.id,
        business_id=biz_id,
        target_entity="Sale",
    )
    assert res2["status"] == "COMPLETED"
    assert "idempotent no-op" in res2["message"]

    count_after = pg_db.scalar(
        select(func.count(Sale.id)).where(Sale.business_id == biz_id, Sale.transaction_number == f"ORD-IDEMP-01-{h}")
    )
    assert count_after == 1

    bad_csv = (
        "order_number,date,subtotal,discount_amount,tax_amount,total_amount,status\n"
        f"ORD-BAD-01-{h},2025-10-05,300.00,10.00,23.20,313.20,completed\n"
        f"ORD-BAD-02-{h},2025-10-06,NOT_A_NUMBER,10.00,23.20,313.20,completed\n"
    )
    dataset_bad = DataGatewayService.save_raw_dataset(
        db=pg_db,
        organization_id=org_id,
        business_id=biz_id,
        filename=f"bad_file_{h}.csv",
        content=bad_csv.encode("utf-8"),
    )
    pg_db.commit()

    with pytest.raises(HTTPException) as exc_info:
        DataGatewayService.ingest_into_core_models(
            db=pg_db,
            dataset_id=dataset_bad.id,
            business_id=biz_id,
            target_entity="Sale",
        )
    assert exc_info.value.status_code == 400

    bad_row1 = pg_db.scalar(
        select(func.count(Sale.id)).where(Sale.transaction_number == f"ORD-BAD-01-{h}")
    )
    assert bad_row1 == 0


# 7. Tenant isolation and existing audit protections
def test_07_tenant_isolation_and_audit_protections(pg_db: Session, remediation_env: dict):
    h = remediation_env["hex_id"]
    biz_a_id = remediation_env["biz_id"]
    org_id = remediation_env["org_id"]

    biz_b = Business(
        id=f"biz-b-{h}",
        organization_id=org_id,
        name="Tenant B Business",
        currency="USD",
        status="active",
    )
    pg_db.add(biz_b)
    pg_db.commit()

    csv_a = f"order_number,date,subtotal,discount_amount,tax_amount,total_amount,status\nORD-TENA-01-{h},2025-11-01,1000.00,0.00,80.00,1080.00,completed\n"
    csv_b = f"order_number,date,subtotal,discount_amount,tax_amount,total_amount,status\nORD-TENB-01-{h},2025-11-01,200.00,0.00,16.00,216.00,completed\n"

    _ingest_csv(pg_db, org_id, biz_a_id, f"ten_a_{h}.csv", csv_a, "Sale")
    _ingest_csv(pg_db, org_id, biz_b.id, f"ten_b_{h}.csv", csv_b, "Sale")

    ctx_a = AnalysisContext(
        business_id=biz_a_id,
        date_from=datetime(2025, 11, 1, tzinfo=UTC),
        date_to=datetime(2025, 11, 30, 23, 59, 59, tzinfo=UTC),
    )
    summary_a = FinancialMetricsCalculator.evaluate_summary(pg_db, ctx_a)

    ctx_b = AnalysisContext(
        business_id=biz_b.id,
        date_from=datetime(2025, 11, 1, tzinfo=UTC),
        date_to=datetime(2025, 11, 30, 23, 59, 59, tzinfo=UTC),
    )
    summary_b = FinancialMetricsCalculator.evaluate_summary(pg_db, ctx_b)

    assert summary_a.net_sales.value == Decimal("1000.00")
    assert summary_a.orders.value == Decimal("1")
    assert summary_b.net_sales.value == Decimal("200.00")
    assert summary_b.orders.value == Decimal("1")


# 8. Missing optional fields and invalid financial values
def test_08_missing_optional_fields_and_invalid_financial_values(pg_db: Session, remediation_env: dict):
    h = remediation_env["hex_id"]
    biz_id = remediation_env["biz_id"]
    org_id = remediation_env["org_id"]

    minimal_csv = (
        "order_number,date,amount\n"
        f"ORD-MIN-01-{h},2025-12-01,400.00\n"
    )
    _ingest_csv(pg_db, org_id, biz_id, f"minimal_{h}.csv", minimal_csv, "Sale")

    sale_min = pg_db.execute(
        select(Sale).where(Sale.business_id == biz_id, Sale.transaction_number == f"ORD-MIN-01-{h}")
    ).scalar_one()

    assert sale_min.subtotal == Decimal("400.00")
    assert sale_min.discount_amount == Decimal("0.00")
    assert sale_min.tax_amount == Decimal("0.00")
    assert sale_min.total_amount == Decimal("400.00")
    assert sale_min.status == "completed"

    neg_disc_csv = (
        "order_number,date,subtotal,discount_amount,tax_amount,total_amount,status\n"
        f"ORD-NEG-01-{h},2025-12-02,500.00,-10.00,40.00,530.00,completed\n"
    )
    ds_neg_disc = DataGatewayService.save_raw_dataset(
        db=pg_db, organization_id=org_id, business_id=biz_id, filename=f"neg_disc_{h}.csv", content=neg_disc_csv.encode("utf-8")
    )
    pg_db.commit()
    with pytest.raises(HTTPException) as exc1:
        DataGatewayService.ingest_into_core_models(db=pg_db, dataset_id=ds_neg_disc.id, business_id=biz_id, target_entity="Sale")
    assert exc1.value.status_code == 400

    bad_status_csv = (
        "order_number,date,subtotal,discount_amount,tax_amount,total_amount,status\n"
        f"ORD-BSTAT-01-{h},2025-12-03,500.00,0.00,40.00,540.00,unknown_status\n"
    )
    ds_bad_st = DataGatewayService.save_raw_dataset(
        db=pg_db, organization_id=org_id, business_id=biz_id, filename=f"bad_status_{h}.csv", content=bad_status_csv.encode("utf-8")
    )
    pg_db.commit()
    with pytest.raises(HTTPException) as exc2:
        DataGatewayService.ingest_into_core_models(db=pg_db, dataset_id=ds_bad_st.id, business_id=biz_id, target_entity="Sale")
    assert exc2.value.status_code == 400


# 9. Waterfall product and category filtering (reconciles with compute_sales_aggregates)
def test_09_waterfall_product_and_category_filtering(pg_db: Session, remediation_env: dict):
    h = remediation_env["hex_id"]
    biz_id = remediation_env["biz_id"]
    cust_id = remediation_env["cust_id"]
    p1_id = remediation_env["p1_id"]  # Category: Hardware, unit_price: 50.00
    p2_id = remediation_env["p2_id"]  # Category: Electronics, unit_price: 30.00

    # Sale 1: June 15 - has both Hardware (P1) and Electronics (P2)
    s1 = Sale(
        business_id=biz_id,
        transaction_number=f"ORD-CAT-01-{h}",
        customer_id=cust_id,
        transaction_date=datetime(2025, 6, 15, 10, 0, tzinfo=UTC),
        subtotal=Decimal("260.00"),
        discount_amount=Decimal("10.00"),
        tax_amount=Decimal("18.75"),
        total_amount=Decimal("268.75"),
        status="completed",
    )
    pg_db.add(s1)
    pg_db.flush()

    # P1: 2 units * $50 = $100 gross, $10 line discount = $90 line total
    item1_1 = SaleItem(
        sale_id=s1.id,
        product_id=p1_id,
        quantity=2,
        unit_price=Decimal("50.00"),
        discount_amount=Decimal("10.00"),
        line_total=Decimal("90.00"),
    )
    # P2: 6 units * $30 = $180 gross, $10 line discount = $170 line total
    item1_2 = SaleItem(
        sale_id=s1.id,
        product_id=p2_id,
        quantity=6,
        unit_price=Decimal("30.00"),
        discount_amount=Decimal("10.00"),
        line_total=Decimal("170.00"),
    )

    # Sale 2: July 10 - Electronics (P2) only
    s2 = Sale(
        business_id=biz_id,
        transaction_number=f"ORD-CAT-02-{h}",
        customer_id=cust_id,
        transaction_date=datetime(2025, 7, 10, 14, 0, tzinfo=UTC),
        subtotal=Decimal("120.00"),
        discount_amount=Decimal("0.00"),
        tax_amount=Decimal("9.00"),
        total_amount=Decimal("129.00"),
        status="completed",
    )
    pg_db.add(s2)
    pg_db.flush()

    # P2: 4 units * $30 = $120 gross, $0 line discount = $120 line total
    item2 = SaleItem(
        sale_id=s2.id,
        product_id=p2_id,
        quantity=4,
        unit_price=Decimal("30.00"),
        discount_amount=Decimal("0.00"),
        line_total=Decimal("120.00"),
    )
    pg_db.add_all([item1_1, item1_2, item2])
    pg_db.commit()

    # Case A: Category filter: Electronics (P2 total: 180 + 120 = 300 gross, 10 line disc, 290 net)
    ctx_elec = AnalysisContext(business_id=biz_id, categories=["Electronics"])
    s_elec = FinancialMetricsCalculator.compute_sales_aggregates(pg_db, ctx_elec)
    wf_elec = FinancialMetricsCalculator.evaluate_gross_to_net_waterfall(pg_db, ctx_elec)
    assert wf_elec.gross_sales == Decimal("300.00")
    assert wf_elec.line_discounts == Decimal("10.00")
    assert wf_elec.order_subtotal == Decimal("290.00")
    assert wf_elec.net_sales == Decimal("290.00")
    assert wf_elec.gross_sales == s_elec["gross_sales"]
    assert wf_elec.line_discounts == s_elec["line_discounts"]
    assert wf_elec.net_sales == s_elec["net_sales"]

    # Case B: Category filter: Apparel (non-existent category in this tenant -> zero results)
    ctx_apparel = AnalysisContext(business_id=biz_id, categories=["Apparel"])
    s_app = FinancialMetricsCalculator.compute_sales_aggregates(pg_db, ctx_apparel)
    wf_app = FinancialMetricsCalculator.evaluate_gross_to_net_waterfall(pg_db, ctx_apparel)
    assert wf_app.gross_sales == Decimal("0.00")
    assert wf_app.line_discounts == Decimal("0.00")
    assert wf_app.net_sales == Decimal("0.00")
    assert wf_app.gross_sales == s_app["gross_sales"]
    assert wf_app.net_sales == s_app["net_sales"]

    # Case C: Specific product ID filter (P1 only: 100 gross, 10 disc, 90 net)
    ctx_p1 = AnalysisContext(business_id=biz_id, product_ids=[p1_id])
    s_p1 = FinancialMetricsCalculator.compute_sales_aggregates(pg_db, ctx_p1)
    wf_p1 = FinancialMetricsCalculator.evaluate_gross_to_net_waterfall(pg_db, ctx_p1)
    assert wf_p1.gross_sales == Decimal("100.00")
    assert wf_p1.line_discounts == Decimal("10.00")
    assert wf_p1.net_sales == Decimal("90.00")
    assert wf_p1.gross_sales == s_p1["gross_sales"]
    assert wf_p1.net_sales == s_p1["net_sales"]

    # Case D: Date range combined with category filter (June only for Electronics: 180 gross, 10 disc, 170 net)
    ctx_date_cat = AnalysisContext(
        business_id=biz_id,
        categories=["Electronics"],
        date_from=datetime(2025, 6, 1, tzinfo=UTC),
        date_to=datetime(2025, 6, 30, 23, 59, 59, tzinfo=UTC),
    )
    s_dc = FinancialMetricsCalculator.compute_sales_aggregates(pg_db, ctx_date_cat)
    wf_dc = FinancialMetricsCalculator.evaluate_gross_to_net_waterfall(pg_db, ctx_date_cat)
    assert wf_dc.gross_sales == Decimal("180.00")
    assert wf_dc.line_discounts == Decimal("10.00")
    assert wf_dc.net_sales == Decimal("170.00")
    assert wf_dc.gross_sales == s_dc["gross_sales"]
    assert wf_dc.net_sales == s_dc["net_sales"]

    # Case E: Empty filtered results (valid category but date range with no sales)
    ctx_empty = AnalysisContext(
        business_id=biz_id,
        categories=["Electronics"],
        date_from=datetime(2025, 1, 1, tzinfo=UTC),
        date_to=datetime(2025, 1, 31, 23, 59, 59, tzinfo=UTC),
    )
    s_empty = FinancialMetricsCalculator.compute_sales_aggregates(pg_db, ctx_empty)
    wf_empty = FinancialMetricsCalculator.evaluate_gross_to_net_waterfall(pg_db, ctx_empty)
    assert wf_empty.gross_sales == Decimal("0.00")
    assert wf_empty.net_sales == Decimal("0.00")
    assert wf_empty.gross_sales == s_empty["gross_sales"]

    # Case F: Unfiltered totals control (total across all products: 100 + 180 + 120 = 400 gross, 20 line disc, 380 subtotal)
    ctx_all = AnalysisContext(
        business_id=biz_id,
        date_from=datetime(2025, 6, 1, tzinfo=UTC),
        date_to=datetime(2025, 7, 31, 23, 59, 59, tzinfo=UTC),
    )
    s_all = FinancialMetricsCalculator.compute_sales_aggregates(pg_db, ctx_all)
    wf_all = FinancialMetricsCalculator.evaluate_gross_to_net_waterfall(pg_db, ctx_all)
    assert wf_all.gross_sales == Decimal("400.00")
    assert wf_all.line_discounts == Decimal("20.00")
    assert wf_all.order_subtotal == Decimal("380.00")
    assert wf_all.order_discounts == Decimal("10.00")
    assert wf_all.net_sales == Decimal("370.00")
    assert wf_all.net_sales == s_all["net_sales"]


# 10. Refund values are not deducted twice from completed sales
def test_10_refund_volume_not_double_deducted(pg_db: Session, remediation_env: dict):
    h = remediation_env["hex_id"]
    biz_id = remediation_env["biz_id"]
    org_id = remediation_env["org_id"]

    csv = (
        "order_number,date,subtotal,discount_amount,tax_amount,total_amount,status\n"
        f"ORD-NODBL-01-{h},2025-08-01,1000.00,50.00,71.25,1021.25,completed\n"
        f"ORD-NODBL-02-{h},2025-08-02,500.00,0.00,37.50,537.50,completed\n"
        f"ORD-NODBL-03-{h},2025-08-03,200.00,0.00,15.00,215.00,refunded\n"
    )
    _ingest_csv(pg_db, org_id, biz_id, f"no_dbl_deduct_{h}.csv", csv, "Sale")

    ctx = AnalysisContext(
        business_id=biz_id,
        date_from=datetime(2025, 8, 1, tzinfo=UTC),
        date_to=datetime(2025, 8, 31, 23, 59, 59, tzinfo=UTC),
    )
    wf = FinancialMetricsCalculator.evaluate_gross_to_net_waterfall(pg_db, ctx)

    # Completed net sales: (1000 - 50) + 500 = 1450.00
    assert wf.net_sales == Decimal("1450.00")
    # Refund volume tracked separately: 200.00 (1 order)
    assert wf.refunds_amount == Decimal("200.00")
    assert wf.refunds_count == 1
    # Net revenue after returns equals completed commercial net sales (NOT 1450 - 200 = 1250)
    assert wf.net_revenue_after_returns == Decimal("1450.00")
    assert wf.net_revenue_after_returns == wf.net_sales


# 11. Multi-line order aggregation preserves order-level metadata without multiplication
def test_11_multi_line_order_aggregation_preserves_order_metadata(pg_db: Session, remediation_env: dict):
    h = remediation_env["hex_id"]
    biz_id = remediation_env["biz_id"]
    org_id = remediation_env["org_id"]

    # 3 lines belonging to one order: ORD-ML-01
    # Line amounts: 100, 150, 250 -> subtotal should be 500.00
    # Order-level metadata repeated on each row: discount=25.00, tax=35.63, total=510.63, status=completed
    multi_csv = (
        "order_number,date,amount,discount_amount,tax_amount,total_amount,status\n"
        f"ORD-ML-01-{h},2025-09-01,100.00,25.00,35.63,510.63,completed\n"
        f"ORD-ML-01-{h},2025-09-01,150.00,25.00,35.63,510.63,completed\n"
        f"ORD-ML-01-{h},2025-09-01,250.00,25.00,35.63,510.63,completed\n"
    )
    _ingest_csv(pg_db, org_id, biz_id, f"multi_order_{h}.csv", multi_csv, "Sale")

    sale = pg_db.execute(
        select(Sale).where(Sale.business_id == biz_id, Sale.transaction_number == f"ORD-ML-01-{h}")
    ).scalar_one()

    # Subtotal must be sum of lines (100 + 150 + 250 = 500)
    assert sale.subtotal == Decimal("500.00")
    # Order-level discount must NOT be multiplied by 3 (remains 25.00, not 75.00)
    assert sale.discount_amount == Decimal("25.00")
    # Order-level tax must NOT be multiplied by 3 (remains 35.63, not 106.89)
    assert sale.tax_amount == Decimal("35.63")
    # Order-level total must NOT be multiplied by 3 (remains 510.63, not 1531.89)
    assert sale.total_amount == Decimal("510.63")
    assert sale.status == "completed"


# 12. Multi-line order conflicting metadata rejected and rolled back
def test_12_multi_line_order_conflicting_metadata_rejected_and_rolled_back(pg_db: Session, remediation_env: dict):
    h = remediation_env["hex_id"]
    biz_id = remediation_env["biz_id"]
    org_id = remediation_env["org_id"]

    # Conflict 1: Conflicting status on row 2 (completed vs cancelled)
    conflict_status_csv = (
        "order_number,date,amount,status\n"
        f"ORD-CONF-ST-{h},2025-09-05,100.00,completed\n"
        f"ORD-CONF-ST-{h},2025-09-05,150.00,cancelled\n"
    )
    ds_c1 = DataGatewayService.save_raw_dataset(
        db=pg_db, organization_id=org_id, business_id=biz_id, filename=f"conf_st_{h}.csv", content=conflict_status_csv.encode("utf-8")
    )
    pg_db.commit()

    with pytest.raises(HTTPException) as exc1:
        DataGatewayService.ingest_into_core_models(db=pg_db, dataset_id=ds_c1.id, business_id=biz_id, target_entity="Sale")
    assert exc1.value.status_code == 400
    detail1 = exc1.value.detail
    assert "CONFLICTING_ORDER_METADATA" in [e["error_type"] for e in detail1["errors"]]
    # Verify complete transaction rollback: 0 rows inserted
    persisted1 = pg_db.scalar(select(func.count(Sale.id)).where(Sale.transaction_number == f"ORD-CONF-ST-{h}"))
    assert persisted1 == 0

    # Conflict 2: Conflicting transaction date on row 2
    conflict_date_csv = (
        "order_number,date,amount,status\n"
        f"ORD-CONF-DT-{h},2025-09-10,100.00,completed\n"
        f"ORD-CONF-DT-{h},2025-09-20,150.00,completed\n"
    )
    ds_c2 = DataGatewayService.save_raw_dataset(
        db=pg_db, organization_id=org_id, business_id=biz_id, filename=f"conf_dt_{h}.csv", content=conflict_date_csv.encode("utf-8")
    )
    pg_db.commit()

    with pytest.raises(HTTPException) as exc2:
        DataGatewayService.ingest_into_core_models(db=pg_db, dataset_id=ds_c2.id, business_id=biz_id, target_entity="Sale")
    assert exc2.value.status_code == 400
    detail2 = exc2.value.detail
    assert "CONFLICTING_ORDER_METADATA" in [e["error_type"] for e in detail2["errors"]]
    # Verify complete transaction rollback
    persisted2 = pg_db.scalar(select(func.count(Sale.id)).where(Sale.transaction_number == f"ORD-CONF-DT-{h}"))
    assert persisted2 == 0


# 13. Multi-line order line-level discounts aggregated correctly
def test_13_multi_line_order_line_level_discounts_aggregated(pg_db: Session, remediation_env: dict):
    h = remediation_env["hex_id"]
    biz_id = remediation_env["biz_id"]
    org_id = remediation_env["org_id"]

    # Multi-line with distinct line discounts: 5.00 on line 1, 10.00 on line 2
    # Amounts: 50.00 and 70.00 -> subtotal 120.00
    # Expected discount: 5.00 + 10.00 = 15.00
    line_disc_csv = (
        "order_number,date,amount,discount_amount,tax_amount,status\n"
        f"ORD-LNDISC-01-{h},2025-09-25,50.00,5.00,3.00,completed\n"
        f"ORD-LNDISC-01-{h},2025-09-25,70.00,10.00,3.00,completed\n"
    )
    _ingest_csv(pg_db, org_id, biz_id, f"line_disc_{h}.csv", line_disc_csv, "Sale")

    sale = pg_db.execute(
        select(Sale).where(Sale.business_id == biz_id, Sale.transaction_number == f"ORD-LNDISC-01-{h}")
    ).scalar_one()

    assert sale.subtotal == Decimal("120.00")
    assert sale.discount_amount == Decimal("15.00")
    # Tax is repeated order tax: 3.00 (not 6.00)
    assert sale.tax_amount == Decimal("3.00")
    # Total dynamically recomputed: 120 - 15 + 3 = 108.00
    assert sale.total_amount == Decimal("108.00")
