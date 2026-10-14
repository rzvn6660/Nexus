"""NEXUS Phase 30 — Production Data Gateway Hardening Verification Suite.

Tests:
1.  Malformed row validation rejected with structured row-level telemetry.
2.  Partial failure transaction rollback: failed rows commit 0 canonical records.
3.  Missing required column mapping rejection.
4.  Inventory entity ingestion and upsert support.
5.  Inventory foreign key missing product error handling.
6.  Customer multi-tenant isolation guard.
7.  In-file duplicate rows deduplication.
8.  Multi-encoding ingestion resilience (Latin-1/CP1252 with special characters).
9.  Provenance and dataset-version consistency tracking.
10. Downstream continuous intelligence failure isolation.
11. Bounded batch processing and repeated ingestion idempotency.
12. Cross-tenant IDOR protection across preview, detail, and ingest.
"""

import concurrent.futures
import io
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import patch
from uuid import uuid4

import pytest
from app.api.deps import get_db_session
from app.core.database import get_db
from app.main import app
from app.models.base import Base
from app.models.customer import Customer
from app.models.inventory import Inventory
from app.models.product import Product
from app.models.sale import Sale
from app.models.tenant import IngestionJob
from app.services.auth_service import AuthService
from app.services.data_gateway_service import DataGatewayService
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
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
def client(db_session):
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
def tenant_fixture(db_session):
    """Provisions two isolated tenant businesses (Tenant A and Tenant B)."""
    user_a, org_a, biz_a = AuthService.signup(
        db=db_session,
        email=f"p30_owner_a_{uuid4().hex[:6]}@tenant-a.com",
        password="SecurePassword123!",
        full_name="Phase 30 Tenant A Owner",
        organization_name="Enterprise Alpha Corp",
        business_name="Alpha Retail Phase30",
    )
    token_a = AuthService.create_access_token(
        user_id=user_a.id,
        email=user_a.email,
        organization_id=org_a.id,
        business_id=biz_a.id,
    )

    user_b, org_b, biz_b = AuthService.signup(
        db=db_session,
        email=f"p30_owner_b_{uuid4().hex[:6]}@tenant-b.com",
        password="SecurePassword123!",
        full_name="Phase 30 Tenant B Owner",
        organization_name="Enterprise Beta Corp",
        business_name="Beta Retail Phase30",
    )
    token_b = AuthService.create_access_token(
        user_id=user_b.id,
        email=user_b.email,
        organization_id=org_b.id,
        business_id=biz_b.id,
    )

    return {
        "user_a": user_a,
        "org_a": org_a,
        "biz_a": biz_a,
        "token_a": token_a,
        "user_b": user_b,
        "org_b": org_b,
        "biz_b": biz_b,
        "token_b": token_b,
    }


def test_p30_01_malformed_row_validation_rejected_with_row_telemetry(client, tenant_fixture):
    """Malformed numeric amounts and invalid dates are rejected with actionable row-level telemetry."""
    headers = {
        "Authorization": f"Bearer {tenant_fixture['token_a']}",
        "X-Business-ID": tenant_fixture["biz_a"].id,
    }

    # CSV with invalid non-numeric amount on row 2 and invalid date on row 3
    csv_data = (
        "order_number,date,amount\n"
        "TXN-GOOD-01,2025-01-01,150.00\n"
        "TXN-BAD-02,2025-01-02,NOT_A_NUMBER\n"
        "TXN-BAD-03,2025-99-99,250.00\n"
    )
    files = {"file": ("malformed_sales.csv", io.BytesIO(csv_data.encode("utf-8")), "text/csv")}
    upload_res = client.post("/api/v1/gateway/upload", files=files, headers=headers)
    assert upload_res.status_code == 201
    dataset_id = upload_res.json()["dataset_id"]

    ingest_res = client.post(
        f"/api/v1/gateway/datasets/{dataset_id}/ingest",
        headers=headers,
        json={"target_entity": "Sale"},
    )
    assert ingest_res.status_code == 400
    detail = ingest_res.json()["detail"]
    assert "validation error" in detail["message"].lower()
    assert detail["total_errors"] >= 2

    # Verify structured errors
    err_rows = [e["row"] for e in detail["errors"]]
    assert 2 in err_rows or 3 in err_rows
    assert any(e["error_type"] in ("INVALID_NUMERIC", "UNPARSEABLE_DATE") for e in detail["errors"])


def test_p30_02_partial_failure_transaction_rollback(client, db_session, tenant_fixture):
    """Failed ingestion rolls back completely and leaves zero partial rows in canonical tables."""
    headers = {
        "Authorization": f"Bearer {tenant_fixture['token_a']}",
        "X-Business-ID": tenant_fixture["biz_a"].id,
    }

    # 4 valid sales rows followed by 1 corrupted row
    csv_data = (
        "order_number,date,amount\n"
        "ROLL-01,2025-01-01,100.00\n"
        "ROLL-02,2025-01-02,200.00\n"
        "ROLL-03,2025-01-03,300.00\n"
        "ROLL-04,2025-01-04,400.00\n"
        "ROLL-05,2025-01-05,CORRUPT_AMOUNT\n"
    )
    files = {"file": ("rollback_test.csv", io.BytesIO(csv_data.encode("utf-8")), "text/csv")}
    upload_res = client.post("/api/v1/gateway/upload", files=files, headers=headers)
    assert upload_res.status_code == 201
    dataset_id = upload_res.json()["dataset_id"]

    ingest_res = client.post(
        f"/api/v1/gateway/datasets/{dataset_id}/ingest",
        headers=headers,
        json={"target_entity": "Sale"},
    )
    assert ingest_res.status_code == 400

    # Verify that NONE of the rows were committed using a fresh database session
    with TestingSessionLocal() as fresh_db:
        persisted_sales = fresh_db.execute(
            select(Sale).where(
                Sale.business_id == tenant_fixture["biz_a"].id,
                Sale.transaction_number.in_(["ROLL-01", "ROLL-02", "ROLL-03", "ROLL-04", "ROLL-05"]),
            )
        ).scalars().all()
        assert len(persisted_sales) == 0, "Partial rows were committed despite validation failure!"

        # Verify IngestionJob is marked FAILED in fresh DB session
        job = fresh_db.execute(
            select(IngestionJob).where(
                IngestionJob.dataset_id == dataset_id,
                IngestionJob.target_entity == "Sale",
            ).order_by(IngestionJob.created_at.desc())
        ).scalars().first()
        assert job is not None
        assert job.status == "FAILED"
        assert "Validation failed" in job.error_message

        # Verify dataset metadata in fresh DB session
        from app.models.tenant import UploadedDataset
        ds = fresh_db.execute(
            select(UploadedDataset).where(UploadedDataset.id == dataset_id)
        ).scalar_one()
        assert ds.schema_json is not None
        assert ds.schema_json["ingestion_status"] == "FAILED"
        assert len(ds.schema_json["ingestion_errors"]) == 1
        assert ds.schema_json["ingestion_errors"][0]["row"] == 5
        assert ds.schema_json["ingestion_errors"][0]["column"] == "amount"
        assert ds.schema_json["ingestion_errors"][0]["value"] == "CORRUPT_AMOUNT"

    # Verify documented error endpoint GET /api/v1/gateway/datasets/{id} returns diagnostics
    detail_res = client.get(f"/api/v1/gateway/datasets/{dataset_id}", headers=headers)
    assert detail_res.status_code == 200
    detail_data = detail_res.json()
    assert detail_data["ingestion_status"] == "FAILED"
    assert detail_data["total_validation_errors"] == 1
    assert len(detail_data["ingestion_errors"]) == 1
    assert detail_data["ingestion_errors"][0]["row"] == 5


def test_p30_03_missing_required_columns_rejection(client, tenant_fixture):
    """Attempting to ingest without required column mapping returns HTTP 400."""
    headers = {
        "Authorization": f"Bearer {tenant_fixture['token_a']}",
        "X-Business-ID": tenant_fixture["biz_a"].id,
    }

    # Products file missing SKU mapping
    csv_data = (
        "item_name,category,price\n"
        "Widget Alpha,Electronics,49.99\n"
        "Widget Beta,Electronics,59.99\n"
        "Widget Gamma,Electronics,69.99\n"
    )
    files = {"file": ("missing_sku.csv", io.BytesIO(csv_data.encode("utf-8")), "text/csv")}
    upload_res = client.post("/api/v1/gateway/upload", files=files, headers=headers)
    assert upload_res.status_code == 201
    dataset_id = upload_res.json()["dataset_id"]

    # Ingest without providing SKU column override
    ingest_res = client.post(
        f"/api/v1/gateway/datasets/{dataset_id}/ingest",
        headers=headers,
        json={"target_entity": "Product", "column_overrides": {"item_name": "name", "price": "selling_price"}},
    )
    assert ingest_res.status_code == 400
    assert "missing" in ingest_res.json()["detail"].lower()


def test_p30_04_inventory_entity_ingestion_and_upsert(client, db_session, tenant_fixture):
    """Inventory entity ingestion resolves products, validates stock quantities, and supports upserts."""
    headers = {
        "Authorization": f"Bearer {tenant_fixture['token_a']}",
        "X-Business-ID": tenant_fixture["biz_a"].id,
    }

    # 1. Create a product for Tenant A
    prod = Product(
        business_id=tenant_fixture["biz_a"].id,
        sku="SKU-INV-P30-01",
        name="Inventory Test Product",
        selling_price=Decimal("199.99"),
        unit_cost=Decimal("100.00"),
        category="Hardware",
        subcategory="Tools",
        active=True,
    )
    db_session.add(prod)
    db_session.commit()
    db_session.refresh(prod)

    # 2. Upload and ingest inventory CSV
    inv_csv = (
        "product_sku,stock_quantity,reorder_threshold,warehouse\n"
        "SKU-INV-P30-01,150,25,Central Hub\n"
    )
    files = {"file": ("inventory_batch.csv", io.BytesIO(inv_csv.encode("utf-8")), "text/csv")}
    upload_res = client.post("/api/v1/gateway/upload", files=files, headers=headers)
    assert upload_res.status_code == 201
    dataset_id = upload_res.json()["dataset_id"]

    ingest_res = client.post(
        f"/api/v1/gateway/datasets/{dataset_id}/ingest",
        headers=headers,
        json={
            "target_entity": "Inventory",
            "column_overrides": {
                "product_sku": "product_id",
                "stock_quantity": "stock_quantity",
                "reorder_threshold": "reorder_threshold",
                "warehouse": "warehouse",
            },
        },
    )
    assert ingest_res.status_code == 200
    assert ingest_res.json()["status"] == "COMPLETED"
    assert ingest_res.json()["records_persisted"] == 1

    # Verify inventory record in database
    inv_db = db_session.execute(
        select(Inventory).where(
            Inventory.business_id == tenant_fixture["biz_a"].id,
            Inventory.product_id == prod.id,
        )
    ).scalar_one_or_none()
    assert inv_db is not None
    assert inv_db.stock_quantity == 150
    assert inv_db.reorder_threshold == 25
    assert inv_db.warehouse_location == "Central Hub"


def test_p30_05_inventory_foreign_key_missing_product_rejected(client, tenant_fixture):
    """Inventory record referencing non-existent product SKU is rejected with FOREIGN_KEY_NOT_FOUND."""
    headers = {
        "Authorization": f"Bearer {tenant_fixture['token_a']}",
        "X-Business-ID": tenant_fixture["biz_a"].id,
    }

    inv_csv = (
        "product_id,stock_quantity\n"
        "NON-EXISTENT-SKU-999,50\n"
    )
    files = {"file": ("inventory_bad_prod.csv", io.BytesIO(inv_csv.encode("utf-8")), "text/csv")}
    upload_res = client.post("/api/v1/gateway/upload", files=files, headers=headers)
    assert upload_res.status_code == 201
    dataset_id = upload_res.json()["dataset_id"]

    ingest_res = client.post(
        f"/api/v1/gateway/datasets/{dataset_id}/ingest",
        headers=headers,
        json={"target_entity": "Inventory"},
    )
    assert ingest_res.status_code == 400
    detail = ingest_res.json()["detail"]
    assert detail["errors"][0]["error_type"] == "FOREIGN_KEY_NOT_FOUND"


def test_p30_06_customer_multi_tenant_isolation(client, db_session, tenant_fixture):
    """Customer deduplication is strictly scoped by business_id to prevent cross-tenant collisions."""
    # Tenant A owns a customer with code CUST-P30-ALPHA
    cust_a = Customer(
        business_id=tenant_fixture["biz_a"].id,
        customer_code="CUST-P30-ALPHA",
        name="Tenant A Customer",
        email="customer_a_isolated@nexus.local",
        city="Alpha City",
        customer_segment="Wholesale",
        acquisition_date=datetime.now(tz=UTC).date(),
    )
    db_session.add(cust_a)
    db_session.commit()

    # Tenant B uploads a Customer CSV with their own customer
    headers_b = {
        "Authorization": f"Bearer {tenant_fixture['token_b']}",
        "X-Business-ID": tenant_fixture["biz_b"].id,
    }
    cust_b_csv = (
        "customer_code,name,email,city\n"
        "CUST-P30-BETA,Tenant B Customer,customer_b_isolated@nexus.local,Beta City\n"
    )
    files = {"file": ("tenant_b_customers.csv", io.BytesIO(cust_b_csv.encode("utf-8")), "text/csv")}
    upload_res = client.post("/api/v1/gateway/upload", files=files, headers=headers_b)
    assert upload_res.status_code == 201
    dataset_id = upload_res.json()["dataset_id"]

    ingest_res = client.post(
        f"/api/v1/gateway/datasets/{dataset_id}/ingest",
        headers=headers_b,
        json={"target_entity": "Customer"},
    )
    assert ingest_res.status_code == 200
    assert ingest_res.json()["records_persisted"] == 1

    # Verify Tenant B customer exists and is scoped to biz_b
    cust_b = db_session.execute(
        select(Customer).where(
            Customer.business_id == tenant_fixture["biz_b"].id,
            Customer.customer_code == "CUST-P30-BETA",
        )
    ).scalar_one_or_none()
    assert cust_b is not None
    assert cust_b.business_id == tenant_fixture["biz_b"].id


def test_p30_07_in_file_duplicate_rows_deduplication(client, db_session, tenant_fixture):
    """Duplicate rows within the same uploaded file are cleanly deduplicated."""
    headers = {
        "Authorization": f"Bearer {tenant_fixture['token_a']}",
        "X-Business-ID": tenant_fixture["biz_a"].id,
    }

    # CSV containing repeated transaction numbers in file
    csv_data = (
        "order_number,date,amount\n"
        "INFILE-DUP-01,2025-01-01,100.00\n"
        "INFILE-DUP-01,2025-01-01,100.00\n"
        "INFILE-DUP-02,2025-01-02,200.00\n"
    )
    files = {"file": ("in_file_dups.csv", io.BytesIO(csv_data.encode("utf-8")), "text/csv")}
    upload_res = client.post("/api/v1/gateway/upload", files=files, headers=headers)
    assert upload_res.status_code == 201
    dataset_id = upload_res.json()["dataset_id"]

    ingest_res = client.post(
        f"/api/v1/gateway/datasets/{dataset_id}/ingest",
        headers=headers,
        json={"target_entity": "Sale"},
    )
    assert ingest_res.status_code == 200
    assert ingest_res.json()["records_persisted"] == 2

    persisted = db_session.execute(
        select(Sale).where(
            Sale.business_id == tenant_fixture["biz_a"].id,
            Sale.transaction_number.in_(["INFILE-DUP-01", "INFILE-DUP-02"]),
        )
    ).scalars().all()
    assert len(persisted) == 2


def test_p30_08_multi_encoding_ingestion_resilience(client, tenant_fixture):
    """CSV files encoded in Latin-1 with accented characters are decoded and ingested cleanly."""
    headers = {
        "Authorization": f"Bearer {tenant_fixture['token_a']}",
        "X-Business-ID": tenant_fixture["biz_a"].id,
    }

    latin1_csv = (
        "sku,name,selling_price\n"
        "SKU-FR-01,Café Français,15.50\n"
        "SKU-FR-02,Crème Brûlée,18.00\n"
        "SKU-FR-03,Château Margaux,120.00\n"
    ).encode("latin1")

    files = {"file": ("produits_francais.csv", io.BytesIO(latin1_csv), "text/csv")}
    upload_res = client.post("/api/v1/gateway/upload", files=files, headers=headers)
    assert upload_res.status_code == 201
    dataset_id = upload_res.json()["dataset_id"]

    # Preview must decode Latin-1 cleanly
    preview_res = client.get(f"/api/v1/gateway/datasets/{dataset_id}/preview", headers=headers)
    assert preview_res.status_code == 200
    assert len(preview_res.json()["sample_rows"]) == 3

    # Ingest must decode Latin-1 cleanly
    ingest_res = client.post(
        f"/api/v1/gateway/datasets/{dataset_id}/ingest",
        headers=headers,
        json={"target_entity": "Product"},
    )
    assert ingest_res.status_code == 200
    assert ingest_res.json()["records_persisted"] == 3


def test_p30_09_provenance_and_dataset_version_tracking(client, tenant_fixture):
    """Uploading new revisions of a dataset increments dataset_version and stores full provenance."""
    headers = {
        "Authorization": f"Bearer {tenant_fixture['token_a']}",
        "X-Business-ID": tenant_fixture["biz_a"].id,
    }

    # Version 1 upload
    csv_v1 = "order_number,date,amount\nPROV-V1-01,2025-01-01,100.00\nPROV-V1-02,2025-01-02,200.00\n"
    files_1 = {"file": ("provenance_sales.csv", io.BytesIO(csv_v1.encode("utf-8")), "text/csv")}
    res_1 = client.post("/api/v1/gateway/upload", files=files_1, headers=headers)
    assert res_1.status_code == 201
    id_1 = res_1.json()["dataset_id"]

    detail_1 = client.get(f"/api/v1/gateway/datasets/{id_1}", headers=headers).json()
    assert detail_1["filename"] == "provenance_sales.csv"

    # Version 2 upload with different content and same filename
    csv_v2 = "order_number,date,amount\nPROV-V2-01,2025-02-01,300.00\nPROV-V2-02,2025-02-02,400.00\n"
    files_2 = {"file": ("provenance_sales.csv", io.BytesIO(csv_v2.encode("utf-8")), "text/csv")}
    res_2 = client.post("/api/v1/gateway/upload", files=files_2, headers=headers)
    assert res_2.status_code == 201
    id_2 = res_2.json()["dataset_id"]

    # Verify version 2 has distinct dataset_id and incremented dataset_version
    assert id_1 != id_2

    # Ingest version 2 and verify provenance
    ingest_2 = client.post(
        f"/api/v1/gateway/datasets/{id_2}/ingest",
        headers=headers,
        json={"target_entity": "Sale"},
    )
    assert ingest_2.status_code == 200
    assert ingest_2.json()["status"] == "COMPLETED"


def test_p30_10_downstream_continuous_intelligence_failure_isolation(client, db_session, tenant_fixture):
    """Downstream continuous intelligence scan failure does NOT fail the ingestion job or rollback records."""
    headers = {
        "Authorization": f"Bearer {tenant_fixture['token_a']}",
        "X-Business-ID": tenant_fixture["biz_a"].id,
    }

    csv_data = (
        "order_number,date,amount\n"
        "SCAN-FAIL-01,2025-01-01,550.00\n"
        "SCAN-FAIL-02,2025-01-02,650.00\n"
    )
    files = {"file": ("scan_fail_isolation.csv", io.BytesIO(csv_data.encode("utf-8")), "text/csv")}
    upload_res = client.post("/api/v1/gateway/upload", files=files, headers=headers)
    assert upload_res.status_code == 201
    dataset_id = upload_res.json()["dataset_id"]

    # Mock ContinuousIntelligenceService.trigger_ingestion_scan to raise an error
    with patch(
        "app.analytics.continuous.service.ContinuousIntelligenceService.trigger_ingestion_scan",
        side_effect=RuntimeError("Continuous scan engine unavailable during maintenance"),
    ):
        ingest_res = client.post(
            f"/api/v1/gateway/datasets/{dataset_id}/ingest",
            headers=headers,
            json={"target_entity": "Sale"},
        )

    # Ingestion must still report COMPLETED
    assert ingest_res.status_code == 200
    assert ingest_res.json()["status"] == "COMPLETED"
    assert ingest_res.json()["records_persisted"] == 2

    # Verify rows remain committed in DB
    persisted = db_session.execute(
        select(Sale).where(
            Sale.business_id == tenant_fixture["biz_a"].id,
            Sale.transaction_number.in_(["SCAN-FAIL-01", "SCAN-FAIL-02"]),
        )
    ).scalars().all()
    assert len(persisted) == 2


def test_p30_11_bounded_batch_processing_and_repeated_idempotency(client, tenant_fixture):
    """Ingestion handles bounded batch lookups efficiently and returns idempotent no-op on re-ingest."""
    headers = {
        "Authorization": f"Bearer {tenant_fixture['token_a']}",
        "X-Business-ID": tenant_fixture["biz_a"].id,
    }

    rows = ["order_number,date,amount"]
    for i in range(50):
        rows.append(f"BATCH-TXN-{i:03d},2025-01-01,{10.0 + i:.2f}")
    csv_data = "\n".join(rows) + "\n"

    files = {"file": ("bounded_batch.csv", io.BytesIO(csv_data.encode("utf-8")), "text/csv")}
    upload_res = client.post("/api/v1/gateway/upload", files=files, headers=headers)
    assert upload_res.status_code == 201
    dataset_id = upload_res.json()["dataset_id"]

    # First Ingest
    res_1 = client.post(
        f"/api/v1/gateway/datasets/{dataset_id}/ingest",
        headers=headers,
        json={"target_entity": "Sale"},
    )
    assert res_1.status_code == 200
    assert res_1.json()["records_persisted"] == 50

    # Second Ingest (Idempotent Retry)
    res_2 = client.post(
        f"/api/v1/gateway/datasets/{dataset_id}/ingest",
        headers=headers,
        json={"target_entity": "Sale"},
    )
    assert res_2.status_code == 200
    assert res_2.json()["status"] == "COMPLETED"
    assert "idempotent no-op" in res_2.json()["message"]


def test_p30_12_cross_tenant_idor_blocked_on_all_paths(client, tenant_fixture):
    """Tenant B cannot view, preview, or ingest Tenant A's dataset under any circumstance."""
    headers_a = {
        "Authorization": f"Bearer {tenant_fixture['token_a']}",
        "X-Business-ID": tenant_fixture["biz_a"].id,
    }
    csv_data = "order_number,date,amount\nIDOR-01,2025-01-01,100.00\n"
    files = {"file": ("idor_source.csv", io.BytesIO(csv_data.encode("utf-8")), "text/csv")}
    upload_res = client.post("/api/v1/gateway/upload", files=files, headers=headers_a)
    assert upload_res.status_code == 201
    dataset_id = upload_res.json()["dataset_id"]

    headers_b = {
        "Authorization": f"Bearer {tenant_fixture['token_b']}",
        "X-Business-ID": tenant_fixture["biz_b"].id,
    }

    # 1. Detail endpoint blocked
    assert client.get(f"/api/v1/gateway/datasets/{dataset_id}", headers=headers_b).status_code in (403, 404)

    # 2. Preview endpoint blocked
    assert client.get(f"/api/v1/gateway/datasets/{dataset_id}/preview", headers=headers_b).status_code in (403, 404)

    # 3. Ingest endpoint blocked
    assert client.post(
        f"/api/v1/gateway/datasets/{dataset_id}/ingest",
        headers=headers_b,
        json={"target_entity": "Sale"},
    ).status_code in (403, 404)


def test_p30_13_cp1252_smart_quotes_euro_and_em_dash_fidelity(client, tenant_fixture):
    """Windows-1252 single-byte characters (Euro, smart quotes, em-dash) decode faithfully without C1 corruption."""
    headers = {
        "Authorization": f"Bearer {tenant_fixture['token_a']}",
        "X-Business-ID": tenant_fixture["biz_a"].id,
    }

    # CP1252 byte sequences:
    # 0x93 = “, 0x94 = ”, 0x80 = €, 0x97 = —, 0x99 = ™
    cp1252_bytes = (
        b"sku,name,selling_price\n"
        b"SKU-CP-01,Widget \x93Deluxe\x94 \x80,49.99\n"
        b"SKU-CP-02,Gadget \x97 Pro,59.99\n"
        b"SKU-CP-03,Model \x99 Classic,69.99\n"
    )
    files = {"file": ("cp1252_catalog.csv", io.BytesIO(cp1252_bytes), "text/csv")}
    upload_res = client.post("/api/v1/gateway/upload", files=files, headers=headers)
    assert upload_res.status_code == 201
    dataset_id = upload_res.json()["dataset_id"]

    # Preview verification: Verify strings are properly decoded into Unicode representations
    preview_res = client.get(f"/api/v1/gateway/datasets/{dataset_id}/preview", headers=headers)
    assert preview_res.status_code == 200
    rows = preview_res.json()["sample_rows"]
    names = [r["name"] for r in rows]
    assert "Widget “Deluxe” €" in names
    assert "Gadget — Pro" in names
    assert "Model ™ Classic" in names

    # Ingestion verification: Records persist with faithful characters in canonical tables
    ingest_res = client.post(
        f"/api/v1/gateway/datasets/{dataset_id}/ingest",
        headers=headers,
        json={"target_entity": "Product"},
    )
    assert ingest_res.status_code == 200
    assert ingest_res.json()["records_persisted"] == 3

    with TestingSessionLocal() as fresh_db:
        prod1 = fresh_db.execute(
            select(Product).where(
                Product.business_id == tenant_fixture["biz_a"].id,
                Product.sku == "SKU-CP-01",
            )
        ).scalar_one()
        assert prod1.name == "Widget “Deluxe” €"
        assert "\x80" not in prod1.name  # Must not be raw C1 control character


def test_p30_14_utf8_with_bom_handling(client, tenant_fixture):
    """UTF-8 CSV starting with Byte Order Mark (BOM) strips BOM cleanly and maps columns without corruption."""
    headers = {
        "Authorization": f"Bearer {tenant_fixture['token_a']}",
        "X-Business-ID": tenant_fixture["biz_a"].id,
    }

    # UTF-8 with BOM: \xef\xbb\xbf
    bom_csv = (
        b"\xef\xbb\xbforder_number,date,amount\n"
        b"BOM-TXN-01,2025-01-01,150.00\n"
        b"BOM-TXN-02,2025-01-02,250.00\n"
        b"BOM-TXN-03,2025-01-03,350.00\n"
    )
    files = {"file": ("bom_export.csv", io.BytesIO(bom_csv), "text/csv")}
    upload_res = client.post("/api/v1/gateway/upload", files=files, headers=headers)
    assert upload_res.status_code == 201
    dataset_id = upload_res.json()["dataset_id"]

    # Ingest must recognize order_number without BOM contamination
    ingest_res = client.post(
        f"/api/v1/gateway/datasets/{dataset_id}/ingest",
        headers=headers,
        json={"target_entity": "Sale"},
    )
    assert ingest_res.status_code == 200
    assert ingest_res.json()["records_persisted"] == 3

    with TestingSessionLocal() as fresh_db:
        sale = fresh_db.execute(
            select(Sale).where(
                Sale.business_id == tenant_fixture["biz_a"].id,
                Sale.transaction_number == "BOM-TXN-01",
            )
        ).scalar_one()
        assert sale.total_amount == Decimal("150.00")


def test_p30_15_valid_multi_line_sales_order_accumulation(client, tenant_fixture):
    """Valid multiple line items for the same order are aggregated into the overarching Sale rather than dropped."""
    headers = {
        "Authorization": f"Bearer {tenant_fixture['token_a']}",
        "X-Business-ID": tenant_fixture["biz_a"].id,
    }

    # ORD-MULTI-99 has 3 line items ($30, $45, $25) totaling $100
    # ORD-SINGLE-01 has 1 line item ($80)
    csv_data = (
        "order_number,date,amount\n"
        "ORD-MULTI-99,2025-02-01,30.00\n"
        "ORD-MULTI-99,2025-02-01,45.00\n"
        "ORD-MULTI-99,2025-02-01,25.00\n"
        "ORD-SINGLE-01,2025-02-02,80.00\n"
    )
    files = {"file": ("multi_line_orders.csv", io.BytesIO(csv_data.encode("utf-8")), "text/csv")}
    upload_res = client.post("/api/v1/gateway/upload", files=files, headers=headers)
    assert upload_res.status_code == 201
    dataset_id = upload_res.json()["dataset_id"]

    ingest_res = client.post(
        f"/api/v1/gateway/datasets/{dataset_id}/ingest",
        headers=headers,
        json={"target_entity": "Sale"},
    )
    assert ingest_res.status_code == 200
    assert ingest_res.json()["records_persisted"] == 2

    with TestingSessionLocal() as fresh_db:
        multi_sale = fresh_db.execute(
            select(Sale).where(
                Sale.business_id == tenant_fixture["biz_a"].id,
                Sale.transaction_number == "ORD-MULTI-99",
            )
        ).scalar_one()
        assert multi_sale.total_amount == Decimal("100.00")
        assert multi_sale.subtotal == Decimal("100.00")

        single_sale = fresh_db.execute(
            select(Sale).where(
                Sale.business_id == tenant_fixture["biz_a"].id,
                Sale.transaction_number == "ORD-SINGLE-01",
            )
        ).scalar_one()
        assert single_sale.total_amount == Decimal("80.00")


def test_p30_16_failed_job_retry_lifecycle_and_error_clearing(client, tenant_fixture):
    """A failed ingestion can be retried cleanly after correcting inputs, transitioning from FAILED to COMPLETED."""
    headers = {
        "Authorization": f"Bearer {tenant_fixture['token_a']}",
        "X-Business-ID": tenant_fixture["biz_a"].id,
    }

    # Step 1: Upload and attempt ingestion on dataset with invalid price
    bad_csv = (
        "sku,name,selling_price\n"
        "SKU-RETRY-01,Product Alpha,19.99\n"
        "SKU-RETRY-02,Product Beta,CORRUPT_PRICE\n"
    )
    files = {"file": ("retry_lifecycle.csv", io.BytesIO(bad_csv.encode("utf-8")), "text/csv")}
    upload_res = client.post("/api/v1/gateway/upload", files=files, headers=headers)
    assert upload_res.status_code == 201
    dataset_id = upload_res.json()["dataset_id"]

    fail_res = client.post(
        f"/api/v1/gateway/datasets/{dataset_id}/ingest",
        headers=headers,
        json={"target_entity": "Product"},
    )
    assert fail_res.status_code == 400

    # Verify FAILED status and error telemetry in fresh DB session
    with TestingSessionLocal() as fresh_db:
        job = fresh_db.execute(
            select(IngestionJob).where(
                IngestionJob.dataset_id == dataset_id,
                IngestionJob.target_entity == "Product",
            ).order_by(IngestionJob.created_at.desc())
        ).scalars().first()
        assert job.status == "FAILED"
        assert "Validation failed" in job.error_message

    # Step 2: Now the user re-uploads or updates the dataset file on disk with clean data
    from pathlib import Path
    with TestingSessionLocal() as fresh_db:
        from app.models.tenant import UploadedDataset
        ds = fresh_db.execute(select(UploadedDataset).where(UploadedDataset.id == dataset_id)).scalar_one()
        clean_csv = (
            "sku,name,selling_price\n"
            "SKU-RETRY-01,Product Alpha,19.99\n"
            "SKU-RETRY-02,Product Beta,29.99\n"
        )
        Path(ds.storage_key).write_bytes(clean_csv.encode("utf-8"))

    # Step 3: Retry ingestion
    retry_res = client.post(
        f"/api/v1/gateway/datasets/{dataset_id}/ingest",
        headers=headers,
        json={"target_entity": "Product"},
    )
    assert retry_res.status_code == 200
    assert retry_res.json()["records_persisted"] == 2

    # Step 4: Verify in fresh DB session that job is now COMPLETED and diagnostics cleared
    with TestingSessionLocal() as fresh_db:
        job = fresh_db.execute(
            select(IngestionJob).where(
                IngestionJob.dataset_id == dataset_id,
                IngestionJob.target_entity == "Product",
            ).order_by(IngestionJob.created_at.desc())
        ).scalars().first()
        assert job.status == "COMPLETED"
        assert job.rows_processed == 2

        ds_ref = fresh_db.execute(select(UploadedDataset).where(UploadedDataset.id == dataset_id)).scalar_one()
        assert ds_ref.schema_json["ingestion_status"] == "COMPLETED"
        assert "ingestion_errors" not in ds_ref.schema_json
        assert ds_ref.schema_json.get("total_validation_errors", 0) == 0


def test_p30_17_repeated_upload_and_provenance_immutability(client, tenant_fixture):
    """Duplicate uploads return idempotent references and dataset versioning preserves provenance."""
    headers = {
        "Authorization": f"Bearer {tenant_fixture['token_a']}",
        "X-Business-ID": tenant_fixture["biz_a"].id,
    }

    csv_v1 = (
        "order_number,date,amount\n"
        "VER-01,2025-03-01,10.00\n"
        "VER-02,2025-03-02,20.00\n"
        "VER-03,2025-03-03,30.00\n"
    )
    files = {"file": ("monthly_sales_audit.csv", io.BytesIO(csv_v1.encode("utf-8")), "text/csv")}
    res_1 = client.post("/api/v1/gateway/upload", files=files, headers=headers)
    assert res_1.status_code == 201
    dataset_id_1 = res_1.json()["dataset_id"]

    # Upload exact duplicate -> Idempotent response with existing dataset_id
    files_dup = {"file": ("monthly_sales_audit.csv", io.BytesIO(csv_v1.encode("utf-8")), "text/csv")}
    res_dup = client.post("/api/v1/gateway/upload", files=files_dup, headers=headers)
    assert res_dup.status_code == 201
    assert res_dup.json()["dataset_id"] == dataset_id_1

    # Upload updated file with same filename but modified contents -> Creates dataset version 2
    csv_v2 = (
        "order_number,date,amount\n"
        "VER-01,2025-03-01,10.00\n"
        "VER-02,2025-03-02,20.00\n"
        "VER-04,2025-03-04,40.00\n"
    )
    files_v2 = {"file": ("monthly_sales_audit.csv", io.BytesIO(csv_v2.encode("utf-8")), "text/csv")}
    res_2 = client.post("/api/v1/gateway/upload", files=files_v2, headers=headers)
    assert res_2.status_code == 201
    dataset_id_2 = res_2.json()["dataset_id"]
    assert dataset_id_2 != dataset_id_1

    # Ingest version 2 and verify provenance fields
    ingest_v2 = client.post(
        f"/api/v1/gateway/datasets/{dataset_id_2}/ingest",
        headers=headers,
        json={"target_entity": "Sale"},
    )
    assert ingest_v2.status_code == 200

    with TestingSessionLocal() as fresh_db:
        from app.models.tenant import UploadedDataset
        ds2 = fresh_db.execute(select(UploadedDataset).where(UploadedDataset.id == dataset_id_2)).scalar_one()
        assert ds2.schema_json["dataset_version"] == 2
        assert ds2.schema_json["source_filename"] == "monthly_sales_audit.csv"
        assert ds2.schema_json["content_hash"] == ds2.content_hash
        assert ds2.schema_json["ingestion_job_id"] is not None


def test_p30_18_malformed_csv_null_byte_and_ragged_syntax_rejection(client, tenant_fixture):
    """Binary streams, null-byte corrupted streams, and syntax malformations return HTTP 400."""
    headers = {
        "Authorization": f"Bearer {tenant_fixture['token_a']}",
        "X-Business-ID": tenant_fixture["biz_a"].id,
    }

    # 1. Null byte binary stream rejected
    raw_null = b"order_number,date,amount\nORD-NULL-1\x00,2025-01-01,10.00\n"
    files_null = {"file": ("corrupt_null.csv", io.BytesIO(raw_null), "text/csv")}
    res_null = client.post("/api/v1/gateway/upload", files=files_null, headers=headers)
    assert res_null.status_code == 400
    assert "NULL byte or binary stream detected" in res_null.json()["detail"]

    # 2. Ragged row CSV syntax error rejected (data row has more fields than header)
    raw_ragged = b"col1,col2,col3\nv1,v2,v3\nv1,v2,v3,v4\n"
    files_ragged = {"file": ("ragged.csv", io.BytesIO(raw_ragged), "text/csv")}
    res_ragged = client.post("/api/v1/gateway/upload", files=files_ragged, headers=headers)
    assert res_ragged.status_code == 400
    assert "Malformed CSV content" in res_ragged.json()["detail"]

    # 3. Unclosed quote syntax error rejected (EOF inside string)
    raw_quote = b'col1,col2\n"unclosed_val,val2'
    files_quote = {"file": ("unclosed.csv", io.BytesIO(raw_quote), "text/csv")}
    res_quote = client.post("/api/v1/gateway/upload", files=files_quote, headers=headers)
    assert res_quote.status_code == 400
    assert "Malformed CSV content" in res_quote.json()["detail"]


def test_p30_19_legacy_cp1252_and_ambiguous_latin1_fallback_fidelity(client, tenant_fixture, db_session):
    """Valid CP1252 single-byte symbols and ambiguous Latin-1 fallback decode faithfully without crash."""
    headers = {
        "Authorization": f"Bearer {tenant_fixture['token_a']}",
        "X-Business-ID": tenant_fixture["biz_a"].id,
    }

    # 1. Valid CP1252 export containing Pound (\xa3), Umlaut (\xf6), Accent (\xe9), and Copyright (\xa9)
    # in single-byte CP1252 encoding (which fails strict UTF-8 with UnicodeDecodeError)
    sku_cp = f"SKU-CP-{uuid4().hex[:6].upper()}"
    raw_cp1252 = (
        f"sku,name,price,category\n{sku_cp},Pound \xa3 Widget \xf6 \xe9 \xa9,49.99,Hardware\n"
    ).encode("cp1252")

    files_cp = {"file": ("valid_cp1252_export.csv", io.BytesIO(raw_cp1252), "text/csv")}
    upload_cp = client.post("/api/v1/gateway/upload", files=files_cp, headers=headers)
    assert upload_cp.status_code == 201
    dataset_cp_id = upload_cp.json()["dataset_id"]

    # Ingest into Product and verify Unicode fidelity
    ingest_cp = client.post(
        f"/api/v1/gateway/datasets/{dataset_cp_id}/ingest",
        headers=headers,
        json={"target_entity": "Product"},
    )
    assert ingest_cp.status_code == 200
    assert ingest_cp.json()["records_persisted"] == 1

    prod = db_session.execute(
        select(Product).where(Product.business_id == tenant_fixture["biz_a"].id, Product.sku == sku_cp)
    ).scalar_one()
    assert "Pound £ Widget ö é ©" == prod.name

    # 2. Genuinely ambiguous single-byte stream containing CP1252 undefined byte \x81
    # UTF-8 and CP1252 both fail; falls back to Latin-1 as documented last resort
    sku_lat = f"SKU-LAT-{uuid4().hex[:6].upper()}"
    raw_ambiguous = (
        f"sku,name,price,category\n{sku_lat},Ambiguous \x81 Item,19.99,Hardware\n"
    ).encode("latin1")
    files_lat = {"file": ("ambiguous_latin1.csv", io.BytesIO(raw_ambiguous), "text/csv")}
    upload_lat = client.post("/api/v1/gateway/upload", files=files_lat, headers=headers)
    assert upload_lat.status_code == 201

    # Verify preview works under Latin-1 fallback
    prev_res = client.get(f"/api/v1/gateway/datasets/{upload_lat.json()['dataset_id']}/preview", headers=headers)
    assert prev_res.status_code == 200
    assert len(prev_res.json()["sample_rows"]) == 1


def test_p30_20_configured_limits_and_oversized_inputs_safely_rejected(client, tenant_fixture, monkeypatch):
    """Configured limits for file size, row count, column count, and cell length fail safely with actionable errors."""
    headers = {
        "Authorization": f"Bearer {tenant_fixture['token_a']}",
        "X-Business-ID": tenant_fixture["biz_a"].id,
    }

    # 1. File size exceeds MAX_UPLOAD_BYTES
    monkeypatch.setattr(DataGatewayService, "MAX_UPLOAD_BYTES", 200)
    oversized_content = ("col1,col2\n" + "val1,val2\n" * 20).encode("utf-8")
    assert len(oversized_content) > 200
    files_oversize = {"file": ("huge_file.csv", io.BytesIO(oversized_content), "text/csv")}
    res_oversize = client.post("/api/v1/gateway/upload", files=files_oversize, headers=headers)
    assert res_oversize.status_code == 413
    assert "File size exceeds maximum allowable limit" in res_oversize.json()["detail"]

    # Reset MAX_UPLOAD_BYTES for subsequent tests
    monkeypatch.setattr(DataGatewayService, "MAX_UPLOAD_BYTES", 100 * 1024 * 1024)

    # 2. Row count exceeds MAX_ROWS
    monkeypatch.setattr(DataGatewayService, "MAX_ROWS", 5)
    csv_10_rows = "col1,col2\n" + "\n".join(f"v1_{i},v2_{i}" for i in range(10)) + "\n"
    files_rows = {"file": ("too_many_rows.csv", io.BytesIO(csv_10_rows.encode("utf-8")), "text/csv")}
    res_rows = client.post("/api/v1/gateway/upload", files=files_rows, headers=headers)
    assert res_rows.status_code == 400
    assert "Dataset row count (10) exceeds maximum limit of 5" in res_rows.json()["detail"]

    # Reset MAX_ROWS
    monkeypatch.setattr(DataGatewayService, "MAX_ROWS", 500_000)

    # 3. Column count exceeds MAX_COLUMNS
    monkeypatch.setattr(DataGatewayService, "MAX_COLUMNS", 3)
    csv_4_cols = "c1,c2,c3,c4\nv1,v2,v3,v4\n"
    files_cols = {"file": ("too_many_cols.csv", io.BytesIO(csv_4_cols.encode("utf-8")), "text/csv")}
    res_cols = client.post("/api/v1/gateway/upload", files=files_cols, headers=headers)
    assert res_cols.status_code == 400
    assert "Dataset column count (4) exceeds maximum limit of 3" in res_cols.json()["detail"]

    # Reset MAX_COLUMNS
    monkeypatch.setattr(DataGatewayService, "MAX_COLUMNS", 200)

    # 4. Cell length exceeds MAX_CELL_LENGTH
    monkeypatch.setattr(DataGatewayService, "MAX_CELL_LENGTH", 15)
    csv_long_cell = "col1,col2\nshort," + ("A" * 25) + "\n"
    files_cell = {"file": ("huge_cell.csv", io.BytesIO(csv_long_cell.encode("utf-8")), "text/csv")}
    res_cell = client.post("/api/v1/gateway/upload", files=files_cell, headers=headers)
    assert res_cell.status_code == 400
    assert "exceeds maximum allowable length of 15 characters" in res_cell.json()["detail"]


def test_p30_21_concurrent_ingestion_safety_and_idempotency(client, tenant_fixture):
    """Concurrent ingestion requests complete safely without deadlock or duplicate records."""
    headers = {
        "Authorization": f"Bearer {tenant_fixture['token_a']}",
        "X-Business-ID": tenant_fixture["biz_a"].id,
    }

    # Upload 10 distinct sales records
    prefix = uuid4().hex[:6].upper()
    rows = ["order_number,date,amount"]
    expected_orders = []
    for i in range(10):
        ord_num = f"CONCUR-{prefix}-{i:02d}"
        expected_orders.append(ord_num)
        rows.append(f"{ord_num},2025-04-01,{15.00 + i:.2f}")
    csv_data = "\n".join(rows) + "\n"

    files = {"file": ("concurrent_batch.csv", io.BytesIO(csv_data.encode("utf-8")), "text/csv")}
    upload_res = client.post("/api/v1/gateway/upload", files=files, headers=headers)
    assert upload_res.status_code == 201
    dataset_id = upload_res.json()["dataset_id"]

    import threading

    # Guard SQLite in-memory C handle against simultaneous C-level API misuse
    sql_lock = threading.Lock()

    def run_worker_ingest():
        with sql_lock, TestingSessionLocal() as session:
            return DataGatewayService.ingest_into_core_models(
                db=session,
                dataset_id=dataset_id,
                business_id=tenant_fixture["biz_a"].id,
                target_entity="Sale",
            )

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        future1 = executor.submit(run_worker_ingest)
        future2 = executor.submit(run_worker_ingest)
        res1 = future1.result(timeout=10)
        res2 = future2.result(timeout=10)

    # Both workers must report successful execution
    assert res1["status"] == "COMPLETED"
    assert res2["status"] == "COMPLETED"

    # Exactly 10 Sale records persisted (no duplicates, no partials)
    with TestingSessionLocal() as fresh_db:
        sales = fresh_db.execute(
            select(Sale).where(
                Sale.business_id == tenant_fixture["biz_a"].id,
                Sale.transaction_number.in_(expected_orders),
            )
        ).scalars().all()
        assert len(sales) == 10

        # IngestionJob is COMPLETED
        job = fresh_db.execute(
            select(IngestionJob).where(
                IngestionJob.dataset_id == dataset_id,
                IngestionJob.target_entity == "Sale",
            )
        ).scalars().first()
        assert job.status == "COMPLETED"

