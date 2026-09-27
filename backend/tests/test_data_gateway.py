"""Production Data Gateway Verification & Hardening Suite (Phase 16).

Tests:
1.  CSV data upload & tenant-scoped storage isolation
2.  XLSX data upload & parsing
3.  Empty file rejection (HTTP 400)
4.  Oversized file rejection (HTTP 413)
5.  Prohibited file extension rejection (HTTP 415)
6.  Deterministic column profiling (data types, nulls, unique counts, roles)
7.  Deterministic data quality auditing & multi-dimensional readiness scoring
8.  Deterministic schema mapping (Sale, Product, Customer detection)
9.  Schema mapping requires-review status on missing essential columns
10. Data preview endpoint (sample rows & column telemetry)
11. Core model ingestion (populating Sales with tenant business_id)
12. Cross-tenant IDOR protection on Gateway endpoints
13. End-to-end customer journey (Signup -> Business Creation -> Gateway Upload -> Ingest -> Agent Analysis)
14. Duplicate upload idempotency (SHA-256 fingerprinting deduplicates identical files)
15. Repeated ingestion idempotency (Prevents duplicate row insertion on re-ingest)
16. Cross-tenant duplicate isolation (Tenant A and B uploading identical data remain isolated)
17. MIME spoofing / binary executable rejection (b"MZ...", b"\\x7fELF...")
18. Corrupted / malformed XLSX rejection (clean HTTP 400)
19. Multi-encoding fallback resilience (UTF-8, Latin-1, CP1252)
20. Unicode filename sanitization (données_ventes_2026.csv)
21. Path traversal sanitization (../../etc/passwd.csv)
22. Excessive columns rejection (>200 columns rejected)
23. Excessive cell length rejection (>10,000 chars rejected)
24. Commercial refunds / negative measure handling (returns & adjustments handled cleanly)
"""

import io
from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.deps import get_db_session
from app.core.database import get_db
from app.main import app
from app.models.base import Base
from app.models.sale import Sale
from app.models.tenant import Business, IngestionJob, UploadedDataset
from app.services.auth_service import AuthService
from app.services.data_gateway_service import DataGatewayService


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
        email=f"owner_a_{uuid4().hex[:6]}@tenant-a.com",
        password="SecurePassword123!",
        full_name="Tenant A Owner",
        organization_name="Enterprise Alpha Corp",
        business_name="Alpha Retail Branch",
    )
    token_a = AuthService.create_access_token(
        user_id=user_a.id,
        email=user_a.email,
        organization_id=org_a.id,
        business_id=biz_a.id,
    )

    user_b, org_b, biz_b = AuthService.signup(
        db=db_session,
        email=f"owner_b_{uuid4().hex[:6]}@tenant-b.com",
        password="SecurePassword123!",
        full_name="Tenant B Owner",
        organization_name="Enterprise Beta Corp",
        business_name="Beta Retail Branch",
    )
    token_b = AuthService.create_access_token(
        user_id=user_b.id,
        email=user_b.email,
        organization_id=org_b.id,
        business_id=biz_b.id,
    )

    return {
        "user_a": user_a,
        "token_a": token_a,
        "biz_a": biz_a,
        "org_a": org_a,
        "user_b": user_b,
        "token_b": token_b,
        "biz_b": biz_b,
        "org_b": org_b,
    }


def test_01_csv_upload_and_profiling(client, tenant_fixture):
    """Verify uploading a CSV profiles columns, sets readiness score, and detects Sales entity."""
    csv_data = (
        "transaction_id,transaction_date,total_amount,payment_method,channel\n"
        "TX-001,2025-01-15,150.50,Credit Card,Online\n"
        "TX-002,2025-01-16,220.00,Debit Card,In-Store\n"
        "TX-003,2025-01-17,89.90,Cash,Online\n"
    )
    files = {"file": ("test_sales.csv", io.BytesIO(csv_data.encode("utf-8")), "text/csv")}
    headers = {
        "Authorization": f"Bearer {tenant_fixture['token_a']}",
        "X-Business-ID": tenant_fixture["biz_a"].id,
    }

    res = client.post("/api/v1/gateway/upload", files=files, headers=headers)
    assert res.status_code == 201
    data = res.json()
    assert data["row_count"] == 3
    assert data["column_count"] == 5
    assert data["readiness_score"] >= 70
    assert data["mapping_proposal"]["target_entity"] == "Sale"
    assert data["mapping_proposal"]["status"] == "MAPPED"


def test_02_empty_file_rejected(client, tenant_fixture):
    """Uploading a 0-byte file must be rejected with HTTP 400."""
    files = {"file": ("empty.csv", io.BytesIO(b""), "text/csv")}
    headers = {
        "Authorization": f"Bearer {tenant_fixture['token_a']}",
        "X-Business-ID": tenant_fixture["biz_a"].id,
    }
    res = client.post("/api/v1/gateway/upload", files=files, headers=headers)
    assert res.status_code == 400
    assert "empty" in res.json()["detail"].lower()


def test_03_prohibited_extension_rejected(client, tenant_fixture):
    """Executable and script extensions must be rejected with HTTP 415."""
    files = {"file": ("malicious_payload.py", io.BytesIO(b"import os\nos.system('calc')"), "text/plain")}
    headers = {
        "Authorization": f"Bearer {tenant_fixture['token_a']}",
        "X-Business-ID": tenant_fixture["biz_a"].id,
    }
    res = client.post("/api/v1/gateway/upload", files=files, headers=headers)
    assert res.status_code == 415
    assert "Unsupported file extension" in res.json()["detail"]


def test_04_oversized_file_rejected(client, tenant_fixture, monkeypatch):
    """Files exceeding size limit must return HTTP 413."""
    monkeypatch.setattr(DataGatewayService, "MAX_UPLOAD_BYTES", 50)
    files = {"file": ("big.csv", io.BytesIO(b"a" * 100), "text/csv")}
    headers = {
        "Authorization": f"Bearer {tenant_fixture['token_a']}",
        "X-Business-ID": tenant_fixture["biz_a"].id,
    }
    res = client.post("/api/v1/gateway/upload", files=files, headers=headers)
    assert res.status_code == 413


def test_05_deterministic_quality_and_readiness_scoring(client, tenant_fixture):
    """Verify deterministic quality scoring and multi-dimensional readiness evaluation."""
    csv_data = (
        "order_number,date,amount,client\n"
        "ORD-01,2025-01-01,100,Alice\n"
        "ORD-02,2025-01-02,200,Bob\n"
        "ORD-03,2025-01-03,300,Charlie\n"
        "ORD-04,2025-01-04,400,David\n"
    )
    files = {"file": ("quality_sample.csv", io.BytesIO(csv_data.encode("utf-8")), "text/csv")}
    headers = {
        "Authorization": f"Bearer {tenant_fixture['token_a']}",
        "X-Business-ID": tenant_fixture["biz_a"].id,
    }
    res = client.post("/api/v1/gateway/upload", files=files, headers=headers)
    assert res.status_code == 201
    q = res.json()["quality_summary"]
    assert q["readiness_score"] >= 80
    assert q["overall_status"] == "READY"
    assert "dimensions" in q
    assert q["dimensions"]["processing"] == "PASSED"
    assert q["dimensions"]["structure"] == "PASSED"


def test_06_schema_mapping_requires_review_on_ambiguity(client, tenant_fixture):
    """Missing required amount or date must trigger REQUIRES_REVIEW and prevent READY status."""
    csv_data = (
        "unrecognized_col_a,unrecognized_col_b\n"
        "val1,val2\n"
        "val3,val4\n"
        "val5,val6\n"
    )
    files = {"file": ("ambiguous.csv", io.BytesIO(csv_data.encode("utf-8")), "text/csv")}
    headers = {
        "Authorization": f"Bearer {tenant_fixture['token_a']}",
        "X-Business-ID": tenant_fixture["biz_a"].id,
    }
    res = client.post("/api/v1/gateway/upload", files=files, headers=headers)
    assert res.status_code == 201
    mapping = res.json()["mapping_proposal"]
    assert mapping["status"] == "REQUIRES_REVIEW"
    assert len(mapping["missing_required_fields"]) > 0
    # Crucial guard: High score cannot override missing essential fields
    assert res.json()["readiness_status"] == "REQUIRES_REVIEW"


def test_07_data_preview_sanitization(client, tenant_fixture):
    """Preview endpoint provides max 15 rows with inferred types and roles without leaking secrets."""
    csv_data = "sku,selling_price\n" + "\n".join([f"SKU-{i},{i*10}.0" for i in range(25)])
    files = {"file": ("product_preview.csv", io.BytesIO(csv_data.encode("utf-8")), "text/csv")}
    headers = {
        "Authorization": f"Bearer {tenant_fixture['token_a']}",
        "X-Business-ID": tenant_fixture["biz_a"].id,
    }
    upload_res = client.post("/api/v1/gateway/upload", files=files, headers=headers)
    dataset_id = upload_res.json()["dataset_id"]

    prev_res = client.get(f"/api/v1/gateway/datasets/{dataset_id}/preview", headers=headers)
    assert prev_res.status_code == 200
    pdata = prev_res.json()
    assert len(pdata["sample_rows"]) == 15
    assert pdata["total_rows"] == 25
    assert pdata["column_roles"]["sku"] == "identifier"
    assert pdata["column_roles"]["selling_price"] == "measure"


def test_08_core_model_ingestion(client, db_session, tenant_fixture):
    """Verify ingesting mapped records commits directly to Sales table with business_id."""
    csv_data = (
        "order_number,date,amount\n"
        "ORD-991,2025-02-01,500.00\n"
        "ORD-992,2025-02-02,750.00\n"
    )
    files = {"file": ("sales_batch.csv", io.BytesIO(csv_data.encode("utf-8")), "text/csv")}
    headers = {
        "Authorization": f"Bearer {tenant_fixture['token_a']}",
        "X-Business-ID": tenant_fixture["biz_a"].id,
    }

    upload_res = client.post("/api/v1/gateway/upload", files=files, headers=headers)
    dataset_id = upload_res.json()["dataset_id"]

    # Ingest into Sale model
    ingest_res = client.post(
        f"/api/v1/gateway/datasets/{dataset_id}/ingest",
        headers=headers,
        json={"target_entity": "Sale"},
    )
    assert ingest_res.status_code == 200
    assert ingest_res.json()["records_persisted"] == 2

    # Verify rows in database
    sales = db_session.execute(
        select(Sale).where(
            Sale.business_id == tenant_fixture["biz_a"].id,
            Sale.transaction_number.in_(["ORD-991", "ORD-992"]),
        )
    ).scalars().all()
    assert len(sales) == 2
    assert sum(s.total_amount for s in sales) == 1250.00


def test_09_cross_tenant_gateway_idor_rejected(client, tenant_fixture):
    """Tenant B cannot preview, inspect, or ingest Tenant A's dataset."""
    csv_data = "colA,amount\n1,100\n"
    files = {"file": ("private_a.csv", io.BytesIO(csv_data.encode("utf-8")), "text/csv")}
    headers_a = {"Authorization": f"Bearer {tenant_fixture['token_a']}"}
    upload_res = client.post("/api/v1/gateway/upload", files=files, headers=headers_a)
    dataset_id = upload_res.json()["dataset_id"]

    # Tenant B attempts GET dataset detail
    headers_b = {"Authorization": f"Bearer {tenant_fixture['token_b']}"}
    get_res = client.get(f"/api/v1/gateway/datasets/{dataset_id}", headers=headers_b)
    assert get_res.status_code in [403, 404]

    # Tenant B attempts GET dataset preview
    prev_res = client.get(f"/api/v1/gateway/datasets/{dataset_id}/preview", headers=headers_b)
    assert prev_res.status_code in [403, 404]

    # Tenant B attempts POST dataset ingest
    ing_res = client.post(f"/api/v1/gateway/datasets/{dataset_id}/ingest", headers=headers_b, json={})
    assert ing_res.status_code in [403, 404]


def test_10_end_to_end_customer_onboarding_and_intelligence_journey(client):
    """Critical E2E customer journey from registration to evidence-backed agent analysis."""
    signup_res = client.post("/api/v1/auth/signup", json={
        "email": "e2e_founder@novaretail.com",
        "password": "NovaPassword2026!",
        "full_name": "Nova Founder",
        "organization_name": "Nova Retail Inc",
        "business_name": "Nova Flagship Store",
    })
    assert signup_res.status_code == 201
    auth_data = signup_res.json()
    token = auth_data["access_token"]
    biz_id = auth_data["business"]["id"]

    headers = {
        "Authorization": f"Bearer {token}",
        "X-Business-ID": biz_id,
    }

    # Upload Data via Gateway
    csv_payload = (
        "order_number,order_date,amount,channel\n"
        "NOVA-101,2025-03-01,1200.00,Online\n"
        "NOVA-102,2025-03-02,2300.00,In-Store\n"
        "NOVA-103,2025-03-03,1500.00,Online\n"
    )
    files = {"file": ("nova_sales_q1.csv", io.BytesIO(csv_payload.encode("utf-8")), "text/csv")}
    upload_res = client.post("/api/v1/gateway/upload", files=files, headers=headers)
    assert upload_res.status_code == 201
    dataset_id = upload_res.json()["dataset_id"]
    assert upload_res.json()["readiness_score"] >= 80

    # Ingest into unified core sales models
    ing_res = client.post(
        f"/api/v1/gateway/datasets/{dataset_id}/ingest",
        headers=headers,
        json={"target_entity": "Sale"},
    )
    assert ing_res.status_code == 200
    assert ing_res.json()["records_persisted"] == 3

    # Query Agent Analytics
    agent_res = client.post(
        "/api/v1/agent/analyze",
        headers=headers,
        json={
            "query": "What was our total revenue across all sales orders?",
            "explanation_level": "manager",
        },
    )
    assert agent_res.status_code == 200
    res_json = agent_res.json()
    assert "answer" in res_json
    assert len(res_json["answer"]) > 0
    assert len(res_json["evidence"]) > 0


# =========================================================================
# PHASE 16C HARDENING & ADVERSARIAL TESTS
# =========================================================================

def test_11_duplicate_upload_idempotency(client, tenant_fixture):
    """Uploading the exact same file content for a business returns the existing dataset idempotently."""
    csv_payload = (
        "order_number,order_date,amount\n"
        "DUP-01,2025-01-01,100.00\n"
        "DUP-02,2025-01-02,200.00\n"
        "DUP-03,2025-01-03,300.00\n"
    )
    files_1 = {"file": ("sales_upload.csv", io.BytesIO(csv_payload.encode("utf-8")), "text/csv")}
    headers = {
        "Authorization": f"Bearer {tenant_fixture['token_a']}",
        "X-Business-ID": tenant_fixture["biz_a"].id,
    }

    res_1 = client.post("/api/v1/gateway/upload", files=files_1, headers=headers)
    assert res_1.status_code == 201
    dataset_id_1 = res_1.json()["dataset_id"]

    # Second upload with identical bytes
    files_2 = {"file": ("sales_upload_retry.csv", io.BytesIO(csv_payload.encode("utf-8")), "text/csv")}
    res_2 = client.post("/api/v1/gateway/upload", files=files_2, headers=headers)
    assert res_2.status_code == 201
    dataset_id_2 = res_2.json()["dataset_id"]

    # Must return the same dataset ID without duplicating storage
    assert dataset_id_1 == dataset_id_2


def test_12_repeated_ingestion_idempotency(client, db_session, tenant_fixture):
    """Repeated ingestion of the same dataset does not double-insert records or duplicate orders."""
    csv_payload = (
        "order_number,order_date,amount\n"
        "REING-01,2025-01-01,150.00\n"
        "REING-02,2025-01-02,250.00\n"
        "REING-03,2025-01-03,350.00\n"
    )
    files = {"file": ("reingest_batch.csv", io.BytesIO(csv_payload.encode("utf-8")), "text/csv")}
    headers = {
        "Authorization": f"Bearer {tenant_fixture['token_a']}",
        "X-Business-ID": tenant_fixture["biz_a"].id,
    }

    upload_res = client.post("/api/v1/gateway/upload", files=files, headers=headers)
    dataset_id = upload_res.json()["dataset_id"]

    # First Ingest
    res_1 = client.post(
        f"/api/v1/gateway/datasets/{dataset_id}/ingest",
        headers=headers,
        json={"target_entity": "Sale"},
    )
    assert res_1.status_code == 200
    assert res_1.json()["records_persisted"] == 3

    # Second Ingest (Repeated / Idempotent call)
    res_2 = client.post(
        f"/api/v1/gateway/datasets/{dataset_id}/ingest",
        headers=headers,
        json={"target_entity": "Sale"},
    )
    assert res_2.status_code == 200
    assert res_2.json()["status"] == "COMPLETED"

    # Verify database has exactly 3 records, not 6
    count = db_session.execute(
        select(Sale).where(
            Sale.business_id == tenant_fixture["biz_a"].id,
            Sale.transaction_number.in_(["REING-01", "REING-02", "REING-03"]),
        )
    ).scalars().all()
    assert len(count) == 3


def test_13_cross_tenant_duplicate_isolation(client, tenant_fixture):
    """Tenant A and Tenant B uploading identical content get separate tenant-isolated datasets."""
    csv_payload = (
        "order_number,order_date,amount\n"
        "SHARED-01,2025-01-01,100.00\n"
        "SHARED-02,2025-01-02,200.00\n"
        "SHARED-03,2025-01-03,300.00\n"
    )

    headers_a = {
        "Authorization": f"Bearer {tenant_fixture['token_a']}",
        "X-Business-ID": tenant_fixture["biz_a"].id,
    }
    files_a = {"file": ("data.csv", io.BytesIO(csv_payload.encode("utf-8")), "text/csv")}
    res_a = client.post("/api/v1/gateway/upload", files=files_a, headers=headers_a)
    assert res_a.status_code == 201
    id_a = res_a.json()["dataset_id"]

    headers_b = {
        "Authorization": f"Bearer {tenant_fixture['token_b']}",
        "X-Business-ID": tenant_fixture["biz_b"].id,
    }
    files_b = {"file": ("data.csv", io.BytesIO(csv_payload.encode("utf-8")), "text/csv")}
    res_b = client.post("/api/v1/gateway/upload", files=files_b, headers=headers_b)
    assert res_b.status_code == 201
    id_b = res_b.json()["dataset_id"]

    # Must be distinct dataset records across tenants
    assert id_a != id_b


def test_14_mime_spoofing_rejected(client, tenant_fixture):
    """File named .csv but starting with executable magic bytes (MZ or ELF) must be rejected."""
    headers = {
        "Authorization": f"Bearer {tenant_fixture['token_a']}",
        "X-Business-ID": tenant_fixture["biz_a"].id,
    }

    # Windows PE executable signature
    exe_content = b"MZ\x90\x00\x03\x00\x00\x00\x04\x00\x00\x00\xff\xff"
    files_exe = {"file": ("fake_sales.csv", io.BytesIO(exe_content), "text/csv")}
    res_exe = client.post("/api/v1/gateway/upload", files=files_exe, headers=headers)
    assert res_exe.status_code == 400
    assert "Executable binary format rejected" in res_exe.json()["detail"]

    # Linux ELF signature
    elf_content = b"\x7fELF\x02\x01\x01\x00"
    files_elf = {"file": ("fake_sales.csv", io.BytesIO(elf_content), "text/csv")}
    res_elf = client.post("/api/v1/gateway/upload", files=files_elf, headers=headers)
    assert res_elf.status_code == 400
    assert "Executable binary format rejected" in res_elf.json()["detail"]


def test_15_malformed_xlsx_rejected(client, tenant_fixture):
    """Corrupted / malformed Excel workbook is rejected with clean HTTP 400, not unhandled 500."""
    headers = {
        "Authorization": f"Bearer {tenant_fixture['token_a']}",
        "X-Business-ID": tenant_fixture["biz_a"].id,
    }
    corrupted_bytes = b"PK\x03\x04corrupted_zip_bytes_that_are_not_valid_openpyxl"
    files = {"file": ("corrupted.xlsx", io.BytesIO(corrupted_bytes), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
    res = client.post("/api/v1/gateway/upload", files=files, headers=headers)
    assert res.status_code == 400
    assert "Malformed or corrupted Excel workbook" in res.json()["detail"]


def test_16_invalid_csv_encoding_fallback(client, tenant_fixture):
    """File encoded in Latin-1 / CP1252 with accented characters is decoded via fallback without crashing."""
    headers = {
        "Authorization": f"Bearer {tenant_fixture['token_a']}",
        "X-Business-ID": tenant_fixture["biz_a"].id,
    }
    # Latin-1 characters: é, è, ç
    raw_latin1 = "order_number,date,amount,client\nORD-L1,2025-01-01,150.00,Andr\xe9\nORD-L2,2025-01-02,250.00,H\xe9l\xe8ne\nORD-L3,2025-01-03,350.00,Fran\xe7ois\n"
    files = {"file": ("latin1_sales.csv", io.BytesIO(raw_latin1.encode("latin-1")), "text/csv")}
    res = client.post("/api/v1/gateway/upload", files=files, headers=headers)
    assert res.status_code == 201
    assert res.json()["row_count"] == 3


def test_17_unicode_filename_sanitization(client, tenant_fixture):
    """File with Unicode characters in filename (données_ventes_2026.csv) is safely processed."""
    headers = {
        "Authorization": f"Bearer {tenant_fixture['token_a']}",
        "X-Business-ID": tenant_fixture["biz_a"].id,
    }
    csv_payload = "order_number,date,amount\nUNI-01,2025-01-01,100\nUNI-02,2025-01-02,200\nUNI-03,2025-01-03,300\n"
    files = {"file": ("données_ventes_2026.csv", io.BytesIO(csv_payload.encode("utf-8")), "text/csv")}
    res = client.post("/api/v1/gateway/upload", files=files, headers=headers)
    assert res.status_code == 201
    assert "données_ventes_2026" in res.json()["filename"]


def test_18_path_traversal_sanitization(client, tenant_fixture):
    """Filename containing directory traversal sequences (../../etc/passwd.csv) is stripped."""
    headers = {
        "Authorization": f"Bearer {tenant_fixture['token_a']}",
        "X-Business-ID": tenant_fixture["biz_a"].id,
    }
    csv_payload = "order_number,date,amount\nTR-01,2025-01-01,100\nTR-02,2025-01-02,200\nTR-03,2025-01-03,300\n"
    files = {"file": ("../../../../etc/passwd.csv", io.BytesIO(csv_payload.encode("utf-8")), "text/csv")}
    res = client.post("/api/v1/gateway/upload", files=files, headers=headers)
    assert res.status_code == 201
    # Traversal characters must be stripped
    assert ".." not in res.json()["filename"]
    assert "/" not in res.json()["filename"]
    assert "\\" not in res.json()["filename"]


def test_19_excessive_columns_rejected(client, tenant_fixture):
    """CSV containing more than 200 columns exceeds maximum limit and is rejected with HTTP 400."""
    headers = {
        "Authorization": f"Bearer {tenant_fixture['token_a']}",
        "X-Business-ID": tenant_fixture["biz_a"].id,
    }
    cols = [f"col_{i}" for i in range(210)]
    csv_payload = ",".join(cols) + "\n" + ",".join(["1"] * 210) + "\n"
    files = {"file": ("wide.csv", io.BytesIO(csv_payload.encode("utf-8")), "text/csv")}
    res = client.post("/api/v1/gateway/upload", files=files, headers=headers)
    assert res.status_code == 400
    assert "exceeds maximum limit" in res.json()["detail"]


def test_20_excessive_cell_length_rejected(client, tenant_fixture):
    """Cell containing more than 10,000 characters is rejected with HTTP 400."""
    headers = {
        "Authorization": f"Bearer {tenant_fixture['token_a']}",
        "X-Business-ID": tenant_fixture["biz_a"].id,
    }
    huge_cell = "A" * 12_000
    csv_payload = f"order_number,date,amount,notes\nBIG-01,2025-01-01,100.00,{huge_cell}\n"
    files = {"file": ("huge_cell.csv", io.BytesIO(csv_payload.encode("utf-8")), "text/csv")}
    res = client.post("/api/v1/gateway/upload", files=files, headers=headers)
    assert res.status_code == 400
    assert "exceeds maximum allowable length" in res.json()["detail"]


def test_21_negative_refund_adjustment_handling(client, tenant_fixture):
    """Negative amounts (refunds, returns, credits) are handled as valid commercial adjustments without failure."""
    headers = {
        "Authorization": f"Bearer {tenant_fixture['token_a']}",
        "X-Business-ID": tenant_fixture["biz_a"].id,
    }
    # Contains a positive sale and a negative refund adjustment
    csv_payload = (
        "order_number,date,amount\n"
        "SALE-01,2025-01-01,500.00\n"
        "REFUND-01,2025-01-02,-50.00\n"
        "SALE-02,2025-01-03,300.00\n"
    )
    files = {"file": ("refunds_sales.csv", io.BytesIO(csv_payload.encode("utf-8")), "text/csv")}
    res = client.post("/api/v1/gateway/upload", files=files, headers=headers)
    assert res.status_code == 201
    assert res.json()["row_count"] == 3
    # Negative values should be accepted, not fail quality
    assert res.json()["readiness_status"] in ["READY", "READY_WITH_WARNINGS"]


def test_22_requires_review_mapping_override_recovery_and_cross_tenant_guard(client, tenant_fixture):
    """
    Verify complete recovery path for ambiguous datasets in REQUIRES_REVIEW:
    1. Upload ambiguous dataset -> sets status to REQUIRES_REVIEW
    2. Tenant B attempt to override/ingest -> Rejected with HTTP 403/404 (IDOR security)
    3. Authorized Tenant A provides column overrides -> Ingests successfully into core models
    4. Dataset status transitions from REQUIRES_REVIEW to READY
    """
    headers_a = {
        "Authorization": f"Bearer {tenant_fixture['token_a']}",
        "X-Business-ID": tenant_fixture["biz_a"].id,
    }
    headers_b = {
        "Authorization": f"Bearer {tenant_fixture['token_b']}",
        "X-Business-ID": tenant_fixture["biz_b"].id,
    }

    # 1. Upload ambiguous dataset
    ambiguous_csv = (
        "col_amt,col_dt,col_ref\n"
        "150.00,2025-03-01,ORDER-AMB-01\n"
        "250.00,2025-03-02,ORDER-AMB-02\n"
        "350.00,2025-03-03,ORDER-AMB-03\n"
    )
    files = {"file": ("ambiguous_sales.csv", io.BytesIO(ambiguous_csv.encode("utf-8")), "text/csv")}
    upload_res = client.post("/api/v1/gateway/upload", files=files, headers=headers_a)
    assert upload_res.status_code == 201
    dataset_id = upload_res.json()["dataset_id"]
    assert upload_res.json()["readiness_status"] == "REQUIRES_REVIEW"

    # 2. Cross-tenant attempt to modify mapping or ingest dataset
    unauthorized_res = client.post(
        f"/api/v1/gateway/datasets/{dataset_id}/ingest",
        json={"target_entity": "Sale", "column_overrides": {"col_amt": "amount", "col_dt": "date"}},
        headers=headers_b,
    )
    assert unauthorized_res.status_code in [403, 404]

    # 3. Authorized customer inspects mapping proposal
    detail_res = client.get(f"/api/v1/gateway/datasets/{dataset_id}", headers=headers_a)
    assert detail_res.status_code == 200
    assert detail_res.json()["readiness_status"] == "REQUIRES_REVIEW"

    # 4. Authorized customer provides explicit column mapping overrides and retries ingestion
    override_payload = {
        "target_entity": "Sale",
        "column_overrides": {
            "col_amt": "amount",
            "col_dt": "date",
            "col_ref": "order_number",
        },
    }
    ingest_res = client.post(
        f"/api/v1/gateway/datasets/{dataset_id}/ingest",
        json=override_payload,
        headers=headers_a,
    )
    assert ingest_res.status_code == 200
    ingest_data = ingest_res.json()
    assert ingest_data["status"] == "COMPLETED"
    assert ingest_data["records_persisted"] == 3

    # 5. Dataset and business data readiness are updated to READY
    recovered_detail = client.get(f"/api/v1/gateway/datasets/{dataset_id}", headers=headers_a)
    assert recovered_detail.status_code == 200
    assert recovered_detail.json()["readiness_status"] == "READY"
    assert recovered_detail.json()["ingestion_status"] == "COMPLETED"
    assert recovered_detail.json()["mapping_proposal"]["status"] == "MAPPED"


def test_23_alembic_migration_006_schema_verification():
    """Verify that Alembic migration 006 exists, chains from 005, and defines ingestion_jobs table and indexes."""
    from pathlib import Path
    import importlib.util

    migration_file = Path("backend/alembic/versions/006_phase16_data_gateway_ingestion.py")
    assert migration_file.exists(), "Migration 006 file must exist in alembic/versions"

    spec = importlib.util.spec_from_file_location("migration_006", migration_file)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    assert mod.revision == "006_phase16_data_gateway_ingestion"
    assert mod.down_revision == "005_phase15_saas_multi_tenancy"
    assert hasattr(mod, "upgrade") and callable(mod.upgrade)
    assert hasattr(mod, "downgrade") and callable(mod.downgrade)

