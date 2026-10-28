"""NEXUS Phase 33 — Real HTTP Business Acceptance Suite.

Validates the complete production-grade SaaS business intelligence lifecycle
using real FastAPI TestClient HTTP requests executed against a live disposable
PostgreSQL 16 + pgvector database.

Strict Requirements:
- Strictly executes against PostgreSQL (asserts dialect == 'postgresql').
- Fails closed when REQUIRE_POSTGRES=true or CI=true if PostgreSQL is unreachable.
- Uses real HTTP endpoints (FastAPI TestClient); never mocks HTTP or database.
- Exercises multi-table retail data from data/sample/ (products, customers, inventory, expenses, sales).
- Verifies mathematical accuracy of deterministic analytics against ground-truth data.
- Enforces multi-tenant IDOR rejection across all endpoints.
- Verifies offline safety invariant: LLM_ALLOW_EXTERNAL_CALLS remains False throughout.
"""

from decimal import Decimal
import io
import os
from pathlib import Path
from uuid import uuid4

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import Session, sessionmaker

from app.api.deps import get_db_session
from app.core.config import settings
from app.core.database import get_db
from app.main import app
from app.models.customer import Customer
from app.models.expense import Expense
from app.models.history import DecisionAuditEvent, DecisionRecord
from app.models.inventory import Inventory
from app.models.product import Product
from app.models.sale import Sale
from app.models.sale_item import SaleItem
from app.models.tenant import (
    Business,
    TenantSemanticModel,
)


# ---------------------------------------------------------------------------
# Strict PostgreSQL Connection & Gate Helpers
# ---------------------------------------------------------------------------

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
        or "postgresql+psycopg://nexus_user:nexus_password@localhost:5432/nexus_test_db"
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


def should_skip_postgres_tests() -> bool:
    """Only allow skipping when in local development without strict PostgreSQL requirement."""
    if is_strict_postgres_required():
        return False
    reachable, _ = check_postgres_connection()
    return not reachable


pytestmark = pytest.mark.skipif(
    should_skip_postgres_tests(),
    reason="Live PostgreSQL daemon is not reachable on configured DATABASE_URL. Verification pending CI run.",
)


# ---------------------------------------------------------------------------
# Module Fixtures: PostgreSQL Engine, Session, and TestClient
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module", autouse=True)
def require_postgres():
    """Ensure live PostgreSQL daemon is verified reachable; fail closed in CI / strict mode."""
    reachable, err = check_postgres_connection()
    if not reachable:
        if is_strict_postgres_required():
            pytest.fail(
                f"PostgreSQL Acceptance Gate Failure: Live PostgreSQL is strictly required "
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
def client(pg_session_factory):
    """FastAPI TestClient wired to PostgreSQL database session."""
    session = pg_session_factory()

    def override_get_db():
        try:
            yield session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_db_session] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
    session.close()


# ---------------------------------------------------------------------------
# Acceptance Suite Context & Test Data Paths
# ---------------------------------------------------------------------------

SAMPLE_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "sample"


class AcceptanceContext:
    """Holds shared state across acceptance steps for Tenant A and Tenant B."""
    # Run identifier for repeatable isolated execution
    run_prefix: str = f"P33_{uuid4().hex[:6].upper()}_"

    # Tenant A (Primary business owner)
    user_a_id: str = ""
    user_a_email: str = ""
    user_a_password: str = "P33SecureOwnerPass2026!"
    org_a_id: str = ""
    biz_a_id: str = ""
    token_a: str = ""

    # Uploaded dataset IDs for Tenant A
    dataset_ids: dict[str, str] = {}

    # Created decision ID for Tenant A
    decision_id: int = 0

    # Tenant B (Competitor for cross-tenant IDOR testing)
    user_b_id: str = ""
    user_b_email: str = ""
    user_b_password: str = "P33CompetitorPass2026!"
    org_b_id: str = ""
    biz_b_id: str = ""
    token_b: str = ""


# ---------------------------------------------------------------------------
# Phase 33 Master Test Class
# ---------------------------------------------------------------------------

class TestPhase33BusinessAcceptance:
    """Full 12-step real HTTP business acceptance on live PostgreSQL 16 + pgvector."""

    # Step 1: User & Business Creation
    def test_01_register_business_owner_and_create_workspace(self, client: TestClient, pg_db: Session) -> None:
        """Register business owner via HTTP POST /api/v1/auth/signup and provision tenant."""
        hex_suffix = uuid4().hex[:8]
        AcceptanceContext.user_a_email = f"p33_owner_{hex_suffix}@apexretail.com"
        org_name = f"Apex Retail Group {hex_suffix}"
        biz_name = f"Apex Specialty Commerce {hex_suffix}"

        signup_payload = {
            "email": AcceptanceContext.user_a_email,
            "password": AcceptanceContext.user_a_password,
            "full_name": "Marcus Vance",
            "organization_name": org_name,
            "business_name": biz_name,
        }

        resp = client.post("/api/v1/auth/signup", json=signup_payload)
        assert resp.status_code == 201, f"Signup failed: {resp.text}"
        data = resp.json()

        assert "access_token" in data
        assert data["token_type"] == "bearer"
        assert data["user"]["email"] == AcceptanceContext.user_a_email
        assert data["organization"]["name"] == org_name
        assert data["business"]["name"] == biz_name

        AcceptanceContext.token_a = data["access_token"]
        AcceptanceContext.user_a_id = data["user"]["id"]
        AcceptanceContext.org_a_id = data["organization"]["id"]
        AcceptanceContext.biz_a_id = data["business"]["id"]

        # Verify PostgreSQL database state directly
        biz = pg_db.execute(select(Business).where(Business.id == AcceptanceContext.biz_a_id)).scalar_one()
        assert biz.organization_id == AcceptanceContext.org_a_id
        assert biz.status == "active"

    # Step 2: Authentication & Token Verification
    def test_02_authenticate_and_verify_jwt_credentials(self, client: TestClient) -> None:
        """Authenticate via HTTP POST /api/v1/auth/login and verify user profile via GET /api/v1/auth/me."""
        login_payload = {
            "email": AcceptanceContext.user_a_email,
            "password": AcceptanceContext.user_a_password,
        }
        resp = client.post("/api/v1/auth/login", json=login_payload)
        assert resp.status_code == 200, f"Login failed: {resp.text}"
        data = resp.json()
        assert "access_token" in data
        assert data["user"]["id"] == AcceptanceContext.user_a_id

        # Verify profile endpoint
        headers = {"Authorization": f"Bearer {AcceptanceContext.token_a}"}
        resp_me = client.get("/api/v1/auth/me", headers=headers)
        assert resp_me.status_code == 200
        me_data = resp_me.json()
        assert me_data["user"]["email"] == AcceptanceContext.user_a_email
        assert len(me_data["tenants"]) >= 1

    # Step 3: Realistic Retail Data Ingestion via Data Gateway API
    def test_03_upload_realistic_retail_csv_files(self, client: TestClient) -> None:
        """Upload realistic retail sample files (products, customers, inventory, expenses, sales) via Data Gateway."""
        assert SAMPLE_DIR.exists(), f"Sample data directory not found at {SAMPLE_DIR}"

        headers = {
            "Authorization": f"Bearer {AcceptanceContext.token_a}",
            "X-Business-ID": AcceptanceContext.biz_a_id,
        }

        prefix = AcceptanceContext.run_prefix

        # Prepare datasets with supported, justified transformations:
        # 1. products.csv: prefix SKU to guarantee isolation against global products_sku_key constraint
        df_prod = pd.read_csv(SAMPLE_DIR / "products.csv")
        prod_id_to_sku = dict(zip(df_prod["id"], df_prod["sku"]))
        df_prod["sku"] = prefix + df_prod["sku"].astype(str)
        prod_bytes = df_prod.to_csv(index=False).encode("utf-8")

        # 2. customers.csv: prefix id, customer_code, and email to guarantee isolation against customers_customer_code_key and email_key
        df_cust = pd.read_csv(SAMPLE_DIR / "customers.csv")
        df_cust["id"] = prefix + df_cust["id"].astype(str)
        df_cust["customer_code"] = prefix + df_cust["customer_code"].astype(str)
        df_cust["email"] = prefix.lower() + df_cust["email"].astype(str)
        cust_bytes = df_cust.to_csv(index=False).encode("utf-8")

        # 3. inventory.csv: map product_id to matching SKU from products.csv to guarantee cross-table relational integrity
        df_inv = pd.read_csv(SAMPLE_DIR / "inventory.csv")
        df_inv["sku"] = df_inv["product_id"].map(lambda pid: prefix + str(prod_id_to_sku[pid]))
        inv_bytes = df_inv.to_csv(index=False).encode("utf-8")

        # 4. expenses.csv: un-modified ground-truth operating expenses
        df_exp = pd.read_csv(SAMPLE_DIR / "expenses.csv")
        exp_bytes = df_exp.to_csv(index=False).encode("utf-8")

        # 5. sales.csv: prefix transaction_number to guarantee isolation against sales_transaction_number_key
        # and resolve natural customer key to match customer catalog
        df_sales = pd.read_csv(SAMPLE_DIR / "sales.csv")
        sale_id_to_txn = dict(zip(df_sales["id"], df_sales["transaction_number"]))
        df_sales["transaction_number"] = prefix + df_sales["transaction_number"].astype(str)
        cust_id_to_code = dict(zip(df_cust["id"], df_cust["customer_code"]))
        df_sales["customer_code"] = df_sales["customer_id"].map(lambda cid: cust_id_to_code[cid])
        df_sales = df_sales.drop(columns=["customer_id"])
        sales_bytes = df_sales.to_csv(index=False).encode("utf-8")

        # 6. sale_items.csv: resolve natural keys using transaction_number and product SKU
        # Never trust source CSV integer IDs as database primary keys!
        df_items = pd.read_csv(SAMPLE_DIR / "sale_items.csv")
        # Map integer sale_id to transaction_number (with prefix)
        df_items["transaction_number"] = df_items["sale_id"].map(lambda sid: prefix + str(sale_id_to_txn[sid]))
        # Map integer product_id to product SKU (with prefix)
        df_items["sku"] = df_items["product_id"].map(lambda pid: prefix + str(prod_id_to_sku[pid]))
        # Remove raw source foreign keys to force resolution via natural keys
        df_items_clean = df_items.drop(columns=["sale_id", "product_id"])
        items_bytes = df_items_clean.to_csv(index=False).encode("utf-8")

        files_to_upload = [
            ("products.csv", "products.csv", prod_bytes),
            ("customers.csv", "customers.csv", cust_bytes),
            ("inventory.csv", "inventory.csv", inv_bytes),
            ("expenses.csv", "expenses.csv", exp_bytes),
            ("sales.csv", "sales.csv", sales_bytes),
            ("sale_items.csv", "sale_items.csv", items_bytes),
        ]

        for filename, key, content in files_to_upload:
            upload_files = {"file": (filename, io.BytesIO(content), "text/csv")}
            resp = client.post("/api/v1/gateway/upload", files=upload_files, headers=headers)
            assert resp.status_code == 201, f"Upload of {filename} failed: {resp.text}"
            upload_data = resp.json()

            assert "dataset_id" in upload_data
            assert upload_data["readiness_status"].lower() in ["ready", "ready_with_warnings"]
            assert upload_data["row_count"] > 0
            assert upload_data["column_count"] > 0
            assert "quality_summary" in upload_data

            AcceptanceContext.dataset_ids[key] = upload_data["dataset_id"]

        assert len(AcceptanceContext.dataset_ids) == 6

    # Step 4: Schema Mapping, Quality Scores, and Ingestion Execution
    def test_04_validate_mapping_and_execute_ingestion(self, client: TestClient) -> None:
        """Execute ingestion through Data Gateway in relational dependency order and verify idempotency."""
        headers = {
            "Authorization": f"Bearer {AcceptanceContext.token_a}",
            "X-Business-ID": AcceptanceContext.biz_a_id,
        }

        # Ingestion sequence in dependency order:
        # 1. Product (catalog foundation)
        # 2. Customer
        # 3. Inventory (references Product SKU)
        # 4. Expense
        # 5. Sale (orders)
        # 6. SaleItem (order lines resolved via natural keys)
        ingest_specs = [
            ("products.csv", "Product", {}),
            ("customers.csv", "Customer", {"customer_code": "customer_code"}),
            ("inventory.csv", "Inventory", {"sku": "sku", "product_id": "ignore"}),
            ("expenses.csv", "Expense", {}),
            ("sales.csv", "Sale", {
                "transaction_number": "order_number",
                "subtotal": "amount",
                "transaction_date": "date",
                "customer_code": "customer_code",
            }),
            ("sale_items.csv", "SaleItem", {
                "transaction_number": "sale_id",
                "sku": "product_id",
                "quantity": "quantity",
                "unit_price": "unit_price",
                "discount_amount": "discount_amount",
                "line_total": "line_total",
            }),
        ]

        for file_key, entity, overrides in ingest_specs:
            dataset_id = AcceptanceContext.dataset_ids[file_key]
            ingest_payload = {
                "target_entity": entity,
                "column_overrides": overrides,
            }
            resp = client.post(
                f"/api/v1/gateway/datasets/{dataset_id}/ingest",
                headers=headers,
                json=ingest_payload,
            )
            assert resp.status_code == 200, f"Ingestion for {entity} failed: {resp.text}"
            ingest_res = resp.json()
            assert ingest_res["status"] == "COMPLETED"
            assert ingest_res["records_persisted"] > 0
            assert ingest_res["target_entity"] == entity

        # Idempotency verification: re-ingesting Sales must be a clean, duplicate-free no-op
        sales_ds_id = AcceptanceContext.dataset_ids["sales.csv"]
        re_ingest_resp = client.post(
            f"/api/v1/gateway/datasets/{sales_ds_id}/ingest",
            headers=headers,
            json={"target_entity": "Sale", "column_overrides": {}},
        )
        assert re_ingest_resp.status_code == 200
        re_data = re_ingest_resp.json()
        assert re_data["status"] == "COMPLETED"
        assert "idempotent no-op" in re_data["message"].lower()

        # Idempotency verification: re-ingesting SaleItem must also be a clean duplicate-free no-op
        items_ds_id = AcceptanceContext.dataset_ids["sale_items.csv"]
        re_ingest_items_resp = client.post(
            f"/api/v1/gateway/datasets/{items_ds_id}/ingest",
            headers=headers,
            json={"target_entity": "SaleItem", "column_overrides": {}},
        )
        assert re_ingest_items_resp.status_code == 200
        re_items_data = re_ingest_items_resp.json()
        assert re_items_data["status"] == "COMPLETED"
        assert "idempotent no-op" in re_items_data["message"].lower()

    # Step 5: Canonical Rows and Relationships in PostgreSQL
    def test_05_verify_canonical_rows_and_relationships_in_postgresql(self, pg_db: Session) -> None:
        """Verify persisted rows, foreign keys, and business scoping directly in PostgreSQL."""
        biz_id = AcceptanceContext.biz_a_id

        # Dialect assertion
        assert pg_db.bind.dialect.name == "postgresql"

        # Row counts match source sample datasets
        product_count = pg_db.scalar(select(func.count(Product.id)).where(Product.business_id == biz_id))
        assert product_count == 150

        customer_count = pg_db.scalar(select(func.count(Customer.id)).where(Customer.business_id == biz_id))
        assert customer_count == 1000

        inventory_count = pg_db.scalar(select(func.count(Inventory.id)).where(Inventory.business_id == biz_id))
        assert inventory_count == 150

        expense_count = pg_db.scalar(select(func.count(Expense.id)).where(Expense.business_id == biz_id))
        assert expense_count == 106

        sales_count = pg_db.scalar(select(func.count(Sale.id)).where(Sale.business_id == biz_id))
        assert sales_count == 3500

        # Canonical SaleItem count and foreign key verification
        sale_items_count = pg_db.scalar(
            select(func.count(SaleItem.id))
            .join(Sale, SaleItem.sale_id == Sale.id)
            .where(Sale.business_id == biz_id)
        )
        assert sale_items_count == 11221, f"Expected 11,221 sale items, found {sale_items_count}"

        # Relational integrity: every Inventory record's product_id points to an existing Product in this business
        inv_prod_ids = pg_db.execute(
            select(Inventory.product_id).where(Inventory.business_id == biz_id)
        ).scalars().all()
        existing_prod_ids = set(
            pg_db.execute(select(Product.id).where(Product.business_id == biz_id)).scalars().all()
        )
        assert set(inv_prod_ids).issubset(existing_prod_ids)

        # Relational integrity: every SaleItem belongs to a Sale and Product strictly owned by this tenant
        item_prod_ids = pg_db.execute(
            select(SaleItem.product_id)
            .join(Sale, SaleItem.sale_id == Sale.id)
            .where(Sale.business_id == biz_id)
        ).scalars().all()
        assert set(item_prod_ids).issubset(existing_prod_ids)

    # Step 6: Activate Semantic Model via Real API
    def test_06_activate_semantic_model_workflow(self, client: TestClient, pg_db: Session) -> None:
        """Trigger semantic model activation via HTTP POST /api/v1/semantic/activate."""
        headers = {
            "Authorization": f"Bearer {AcceptanceContext.token_a}",
            "X-Business-ID": AcceptanceContext.biz_a_id,
        }

        resp = client.post("/api/v1/semantic/activate", json={}, headers=headers)
        assert resp.status_code == 200, f"Semantic activation failed: {resp.text}"
        data = resp.json()

        assert data["business_id"] == AcceptanceContext.biz_a_id
        assert data["version"] >= 1

        # If review is required, approve via HTTP review endpoint
        if data["status"] == "REQUIRES_REVIEW":
            revisions_resp = client.get("/api/v1/semantic/revisions", headers=headers)
            assert revisions_resp.status_code == 200
            revs = revisions_resp.json()
            rev_id = revs[0]["id"]
            appr_resp = client.post(
                f"/api/v1/semantic/revisions/{rev_id}/approve",
                json={"comment": "Approved in Phase 33 Acceptance test"},
                headers=headers,
            )
            assert appr_resp.status_code == 200
            assert appr_resp.json()["new_status"] == "ACTIVE"

        # Verify active semantic model in database
        active_model = pg_db.execute(
            select(TenantSemanticModel).where(
                TenantSemanticModel.business_id == AcceptanceContext.biz_a_id,
                TenantSemanticModel.status == "ACTIVE",
            )
        ).scalars().first()
        assert active_model is not None
        assert "Sale" in active_model.entities_json
        assert "Product" in active_model.entities_json
        assert "Customer" in active_model.entities_json

    # Step 7: Query Deterministic Analytics & Mathematical Verification
    def test_07_query_deterministic_analytics_and_verify_mathematics(self, client: TestClient, pg_db: Session) -> None:
        """Query HTTP GET /api/v1/analytics/summary and verify exact mathematical formulas and product metrics against ground truth."""
        headers = {
            "Authorization": f"Bearer {AcceptanceContext.token_a}",
            "X-Business-ID": AcceptanceContext.biz_a_id,
        }

        resp = client.get("/api/v1/analytics/summary", headers=headers)
        assert resp.status_code == 200, f"Analytics summary failed: {resp.text}"
        data = resp.json()

        assert data["success"] is True
        summary = data["data"]
        evidence = data["evidence"]

        # Ground-truth mathematical assertions derived directly from sales.csv & sale_items.csv:
        # Completed sales only (status IN ('completed', 'shipped')):
        # Completed orders = 3,299 (91 refunded, 77 pending, 33 cancelled excluded from commercial sales)
        # Gross line sales = 18,502,059.67
        # Line discounts = 1,547,536.24
        # Order subtotal = 16,954,523.43
        # Order discounts = 61,857.66
        # Net commercial revenue = 16,954,523.43 - 61,857.66 = 16,892,665.77
        # AOV = 16,892,665.77 / 3,299 = 5,120.54
        # Completed units sold = 198,198
        # Sales tax liability = 1,266,949.84
        # Total billed amount = 16,892,665.77 + 1,266,949.84 = 18,159,615.61
        net_sales_val = Decimal(str(summary["net_sales"]["value"]))
        orders_val = int(summary["orders"]["value"])
        aov_val = Decimal(str(summary["average_order_value"]["value"]))
        units_sold_val = int(summary["units_sold"]["value"])
        tax_val = Decimal(str(summary["tax_amount"]["value"]))
        total_billed_val = Decimal(str(summary["total_billed"]["value"]))

        assert net_sales_val == Decimal("16892665.77")
        assert orders_val == 3299
        assert aov_val == Decimal("5120.54")
        assert units_sold_val == 198198
        assert tax_val == Decimal("1266949.84")
        assert total_billed_val == Decimal("18159615.61")

        # Direct PostgreSQL validation across ALL 3,500 ingested rows (unfiltered DB layer):
        biz_id = AcceptanceContext.biz_a_id
        db_total_sales_rows = pg_db.scalar(
            select(func.count(Sale.id)).where(Sale.business_id == biz_id)
        )
        assert db_total_sales_rows == 3500

        db_total_tax_preserved = pg_db.scalar(
            select(func.sum(Sale.tax_amount)).where(Sale.business_id == biz_id)
        )
        assert Decimal(str(db_total_tax_preserved)) == Decimal("1330541.07")

        db_total_billed_preserved = pg_db.scalar(
            select(func.sum(Sale.total_amount)).where(Sale.business_id == biz_id)
        )
        assert Decimal(str(db_total_billed_preserved)) == Decimal("19071089.50")

        db_total_units = pg_db.scalar(
            select(func.sum(SaleItem.quantity))
            .join(Sale, SaleItem.sale_id == Sale.id)
            .where(Sale.business_id == biz_id)
        )
        assert db_total_units == 208641

        db_total_line_revenue = pg_db.scalar(
            select(func.sum(SaleItem.line_total))
            .join(Sale, SaleItem.sale_id == Sale.id)
            .where(Sale.business_id == biz_id)
        )
        assert Decimal(str(db_total_line_revenue)) == Decimal("17803706.80")

        # Verify commercial Gross-to-Net waterfall endpoint via real HTTP API
        wf_resp = client.get("/api/v1/analytics/waterfall/gross-to-net", headers=headers)
        assert wf_resp.status_code == 200, f"Waterfall API failed: {wf_resp.text}"
        wf_data = wf_resp.json()["data"]
        assert Decimal(str(wf_data["gross_sales"])) == Decimal("18502059.67")
        assert Decimal(str(wf_data["line_discounts"])) == Decimal("1547536.24")
        assert Decimal(str(wf_data["order_subtotal"])) == Decimal("16954523.43")
        assert Decimal(str(wf_data["order_discounts"])) == Decimal("61857.66")
        assert Decimal(str(wf_data["total_discounts"])) == Decimal("1609393.90")
        assert Decimal(str(wf_data["net_sales"])) == Decimal("16892665.77")
        assert Decimal(str(wf_data["tax_amount"])) == Decimal("1266949.84")
        assert Decimal(str(wf_data["total_billed"])) == Decimal("18159615.61")
        assert Decimal(str(wf_data["refunds_amount"])) == Decimal("310096.91")
        assert wf_data["refunds_count"] == 91
        assert Decimal(str(wf_data["net_revenue_after_returns"])) == Decimal("16892665.77")

        # Verify product-level performance rankings via real HTTP API
        prod_resp = client.get("/api/v1/analytics/products?ranking_metric=revenue&limit=50", headers=headers)
        assert prod_resp.status_code == 200, f"Product analytics query failed: {prod_resp.text}"
        prod_envelope = prod_resp.json()
        assert prod_envelope["success"] is True
        prod_items = prod_envelope["data"]
        assert len(prod_items) > 0

        # Verify top product revenue and units sold
        top_product = prod_items[0]
        assert float(str(top_product["revenue"])) > 0
        assert int(top_product["units_sold"]) > 0
        assert top_product["rank"] == 1

        # Mathematical consistency assertion
        derived_aov = round(net_sales_val / orders_val, 2)
        assert derived_aov == aov_val

        # Numerical evidence traceability
        assert "generated_at" in evidence
        assert "checksum" in evidence
        assert "calculation" in evidence
        assert "analysis_id" in evidence

    # Step 8: Predictive Forecasting, Horizon Bounds, and Abstention Behavior
    def test_08_run_forecasting_and_verify_horizons_and_abstention(self, client: TestClient) -> None:
        """Verify time-series forecasting endpoint, confidence bounds, and horizon abstention via real API."""
        headers = {
            "Authorization": f"Bearer {AcceptanceContext.token_a}",
            "X-Business-ID": AcceptanceContext.biz_a_id,
        }

        # 1. Valid forecast query across supported 3-month horizon
        forecast_payload = {
            "target_metric": "revenue",
            "frequency": "monthly",
            "forecast_horizon": 3,
            "confidence_level": 0.95,
            "reference_date": "2026-09-01",
        }
        resp = client.post("/api/v1/forecast", json=forecast_payload, headers=headers)
        assert resp.status_code == 200, f"Forecast request failed: {resp.text}"
        fc_data = resp.json()

        assert fc_data["target_metric"] == "revenue"
        assert fc_data["status"] in ["completed", "ForecastStatus.COMPLETED", "success"]
        assert len(fc_data["predictions"]) == 3

        for pred in fc_data["predictions"]:
            assert "period_end" in pred
            p_val = pred["point_forecast"]
            lower = pred["lower_bound"]
            upper = pred["upper_bound"]
            assert lower <= p_val <= upper, f"Confidence interval violated: {lower} <= {p_val} <= {upper}"

        # 2. Out-of-bounds horizon rejection (> MAX_FORECAST_HORIZON=24) -> HTTP 422
        invalid_payload = {
            "target_metric": "revenue",
            "frequency": "monthly",
            "forecast_horizon": 48,
        }
        resp_invalid = client.post("/api/v1/forecast", json=invalid_payload, headers=headers)
        assert resp_invalid.status_code == 422

    # Step 9: Decision Creation, Approval, and Immutable Audit Events
    def test_09_decision_lifecycle_and_immutable_audit_events(self, client: TestClient, pg_db: Session) -> None:
        """Create decision, record human review, and verify immutable audit trail and hash chain."""
        headers = {
            "Authorization": f"Bearer {AcceptanceContext.token_a}",
            "X-Business-ID": AcceptanceContext.biz_a_id,
        }

        # 1. Create decision proposal
        decision_payload = {
            "recommendation_text": "Introduce seasonal coffee bundle to improve AOV across accessories",
            "recommendation_type": "PRICING_OPTIMIZATION",
            "recommendation_payload": {
                "point_recommendation": {"bundle_discount_pct": 10},
                "assumptions": ["Customer demand increases by 5%"],
            },
            "baseline_metrics_snapshot": {
                "metrics": {"net_sales": 17803706.80, "aov": 5086.77},
            },
        }
        resp = client.post("/api/v1/history/decisions", json=decision_payload, headers=headers)
        assert resp.status_code == 201, f"Create decision failed: {resp.text}"
        dec_data = resp.json()
        assert dec_data["status"] == "PENDING"
        decision_id = dec_data["id"]
        AcceptanceContext.decision_id = decision_id

        # 2. Human approval via PATCH /api/v1/history/decisions/{id}
        review_payload = {
            "status": "APPROVED",
            "reviewer_notes": "Reviewed and approved by Operations Director Marcus Vance.",
        }
        resp_patch = client.patch(f"/api/v1/history/decisions/{decision_id}", json=review_payload, headers=headers)
        assert resp_patch.status_code == 200, f"Review decision failed: {resp_patch.text}"
        patch_data = resp_patch.json()
        assert patch_data["status"] == "APPROVED"
        assert patch_data["reviewer_notes"] == review_payload["reviewer_notes"]

        # 3. Retrieve immutable audit events via API
        resp_audit = client.get(f"/api/v1/history/decisions/{decision_id}/audit-events", headers=headers)
        assert resp_audit.status_code == 200
        audit_events = resp_audit.json()
        assert len(audit_events) >= 2  # RECOMMENDATION_CREATED and HUMAN_APPROVED
        event_types = [e["event_type"] for e in audit_events]
        assert "RECOMMENDATION_CREATED" in event_types
        assert "HUMAN_APPROVED" in event_types

        # 4. Cryptographic audit chain verification via API
        resp_verify = client.get(f"/api/v1/history/decisions/{decision_id}/verify-audit-chain", headers=headers)
        assert resp_verify.status_code == 200
        verify_data = resp_verify.json()
        assert verify_data["is_valid"] is True
        assert verify_data["total_events"] >= 2

        # Direct database assertion on DecisionRecord and DecisionAuditEvent
        db_dec = pg_db.get(DecisionRecord, decision_id)
        assert db_dec.status == "APPROVED"
        assert db_dec.business_id == AcceptanceContext.biz_a_id

        # 5. Gap 1 Remediation: Direct SQL UPDATE & DELETE Immutability Trigger Verification
        # Verify PostgreSQL trigger trg_protect_audit_events rejects direct UPDATE mutations
        with pytest.raises(Exception) as exc_update:
            pg_db.execute(
                text("UPDATE decision_audit_events SET event_type = 'CORRUPTED_EVENT' WHERE decision_id = :d_id"),
                {"d_id": decision_id},
            )
            pg_db.flush()
        pg_db.rollback()
        err_msg_update = str(exc_update.value).lower()
        assert any(
            phrase in err_msg_update
            for phrase in ["append-only", "strictly forbidden", "trg_deny_audit_mutation", "trigger"]
        ), f"UPDATE was not rejected by immutability trigger: {err_msg_update}"

        # Verify PostgreSQL trigger trg_protect_audit_events rejects direct DELETE mutations
        with pytest.raises(Exception) as exc_delete:
            pg_db.execute(
                text("DELETE FROM decision_audit_events WHERE decision_id = :d_id"),
                {"d_id": decision_id},
            )
            pg_db.flush()
        pg_db.rollback()
        err_msg_delete = str(exc_delete.value).lower()
        assert any(
            phrase in err_msg_delete
            for phrase in ["append-only", "strictly forbidden", "trg_deny_audit_mutation", "trigger"]
        ), f"DELETE was not rejected by immutability trigger: {err_msg_delete}"

        # Confirm the failed mutations did not alter or delete any audit records
        audit_events_post_attack = pg_db.execute(
            select(DecisionAuditEvent).where(DecisionAuditEvent.decision_id == decision_id)
        ).scalars().all()
        assert len(audit_events_post_attack) >= 2
        assert all(e.event_type != "CORRUPTED_EVENT" for e in audit_events_post_attack)

        # Cryptographic chain verification still passes cleanly after attempted mutations
        resp_verify_final = client.get(f"/api/v1/history/decisions/{decision_id}/verify-audit-chain", headers=headers)
        assert resp_verify_final.status_code == 200
        assert resp_verify_final.json()["is_valid"] is True

    # Step 10: Continuous Intelligence Scan and Findings
    def test_10_continuous_intelligence_scan_and_findings(self, client: TestClient) -> None:
        """Run continuous intelligence scan and verify finding generation via real API."""
        headers = {
            "Authorization": f"Bearer {AcceptanceContext.token_a}",
            "X-Business-ID": AcceptanceContext.biz_a_id,
        }

        # Trigger on-demand business metric scan
        resp = client.post("/api/v1/continuous/scan", json={}, headers=headers)
        assert resp.status_code == 200, f"Continuous scan failed: {resp.text}"
        scan_data = resp.json()
        assert scan_data["status"] == "COMPLETED"
        assert scan_data["business_id"] == AcceptanceContext.biz_a_id
        assert len(scan_data["metrics_scanned"]) >= 1

        # Query findings endpoint
        resp_findings = client.get("/api/v1/continuous/findings", headers=headers)
        assert resp_findings.status_code == 200
        findings_data = resp_findings.json()
        assert "items" in findings_data
        assert "total_count" in findings_data

    # Step 11: Cross-Tenant Isolation Defense (Multi-Tenant IDOR Denial)
    def test_11_cross_tenant_isolation_enforcement(self, client: TestClient) -> None:
        """Ensure an unrelated tenant is rejected with HTTP 403 Forbidden across all protected endpoints."""
        # 1. Register Tenant B (Competitor)
        hex_suffix = uuid4().hex[:8]
        AcceptanceContext.user_b_email = f"p33_competitor_{hex_suffix}@competitor.com"
        signup_b = {
            "email": AcceptanceContext.user_b_email,
            "password": AcceptanceContext.user_b_password,
            "full_name": "Intruding Analyst",
            "organization_name": f"Competitor Corp {hex_suffix}",
            "business_name": f"Competitor Business {hex_suffix}",
        }
        resp_b = client.post("/api/v1/auth/signup", json=signup_b)
        assert resp_b.status_code == 201
        data_b = resp_b.json()
        AcceptanceContext.token_b = data_b["access_token"]
        AcceptanceContext.biz_b_id = data_b["business"]["id"]

        headers_b = {
            "Authorization": f"Bearer {AcceptanceContext.token_b}",
            "X-Business-ID": AcceptanceContext.biz_b_id,
        }

        # Attack 1: Tenant B tries to view Tenant A's dataset
        tenant_a_ds_id = AcceptanceContext.dataset_ids["sales.csv"]
        resp_attack_1 = client.get(f"/api/v1/gateway/datasets/{tenant_a_ds_id}", headers=headers_b)
        assert resp_attack_1.status_code == 403, f"Expected 403, got {resp_attack_1.status_code}"

        # Attack 2: Tenant B tries to ingest Tenant A's dataset
        resp_attack_2 = client.post(
            f"/api/v1/gateway/datasets/{tenant_a_ds_id}/ingest",
            json={"target_entity": "Sale"},
            headers=headers_b,
        )
        assert resp_attack_2.status_code == 403, f"Expected 403, got {resp_attack_2.status_code}"

        # Attack 3: Tenant B tries to read Tenant A's decision
        tenant_a_dec_id = AcceptanceContext.decision_id
        resp_attack_3 = client.get(f"/api/v1/history/decisions/{tenant_a_dec_id}", headers=headers_b)
        assert resp_attack_3.status_code == 403, f"Expected 403, got {resp_attack_3.status_code}"

        # Attack 4: Tenant B tries to update/approve Tenant A's decision
        resp_attack_4 = client.patch(
            f"/api/v1/history/decisions/{tenant_a_dec_id}",
            json={"status": "REJECTED", "reviewer_notes": "Unauthorized modification"},
            headers=headers_b,
        )
        assert resp_attack_4.status_code == 403, f"Expected 403, got {resp_attack_4.status_code}"

        # Attack 5: Tenant B tries to run continuous scan specifying Tenant A's business_id
        spoofed_headers = {
            "Authorization": f"Bearer {AcceptanceContext.token_b}",
            "X-Business-ID": AcceptanceContext.biz_a_id,
        }
        resp_attack_5 = client.post("/api/v1/continuous/scan", json={}, headers=spoofed_headers)
        assert resp_attack_5.status_code == 403, f"Expected 403, got {resp_attack_5.status_code}"

        # Attack 6: Tenant B tries to view Tenant A's analytics summary
        resp_attack_6 = client.get("/api/v1/analytics/summary", headers=spoofed_headers)
        assert resp_attack_6.status_code == 403, f"Expected 403, got {resp_attack_6.status_code}"

    # Step 12: Offline Safety Invariant
    def test_12_offline_safety_invariant_remains_enforced(self) -> None:
        """Verify LLM_ALLOW_EXTERNAL_CALLS remains strictly False throughout execution."""
        assert getattr(settings, "LLM_ALLOW_EXTERNAL_CALLS", False) is False
        assert os.getenv("LLM_ALLOW_EXTERNAL_CALLS", "False").strip().lower() in ("false", "0")
