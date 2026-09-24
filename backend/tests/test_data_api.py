"""Integration tests for Data Layer API endpoints."""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session


def test_api_data_health(client: TestClient, seeded_db_session: Session) -> None:
    """Validate GET /api/v1/data/health returns readiness status and table list."""
    response = client.get("/api/v1/data/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] in ("ready", "degraded")
    assert data["layer"] == "data_layer"
    assert data["registered_models"] == 6
    assert "customers" in data["tables"]
    assert "sales" in data["tables"]


def test_api_data_tables(client: TestClient, seeded_db_session: Session) -> None:
    """Validate GET /api/v1/data/tables returns table summaries."""
    response = client.get("/api/v1/data/tables")
    assert response.status_code == 200
    tables = response.json()
    assert len(tables) == 6
    table_names = [t["table_name"] for t in tables]
    assert "customers" in table_names
    assert "products" in table_names
    assert "sales" in table_names
    assert "sale_items" in table_names
    assert "inventory" in table_names
    assert "expenses" in table_names


def test_api_data_profile_endpoint(client: TestClient, seeded_db_session: Session) -> None:
    """Validate GET /api/v1/data/profile/{dataset} generates statistical profile."""
    response = client.get("/api/v1/data/profile/customers")
    assert response.status_code == 200
    profile = response.json()
    assert profile["table_name"] == "customers"
    assert profile["total_rows"] >= 2
    assert "email" in profile["columns"]
    assert "customer_segment" in profile["columns"]


def test_api_data_profile_not_found(client: TestClient) -> None:
    """Validate 404 response on unknown dataset profile request."""
    response = client.get("/api/v1/data/profile/unknown_table_xyz")
    assert response.status_code == 404


def test_api_data_quality_endpoint(client: TestClient, seeded_db_session: Session) -> None:
    """Validate GET /api/v1/data/quality/{dataset} generates quality scorecard."""
    response = client.get("/api/v1/data/quality/customers")
    assert response.status_code == 200
    report = response.json()
    assert report["dataset_name"] == "customers"
    assert report["status"] == "PASSED"
    assert report["checks_executed"] > 0


def test_api_data_ingest_csv_endpoint(client: TestClient) -> None:
    """Validate POST /api/v1/data/ingest/csv processes uploaded CSV."""
    csv_bytes = (
        b"customer_code,name,email,phone,city,customer_segment,acquisition_date\n"
        b"CUST-API-1,Api User,api@nexus.ai,555-9999,San Francisco,Corporate,2023-04-01\n"
    )

    files = {
        "file": ("test_customers.csv", csv_bytes, "text/csv"),
    }
    data = {
        "dataset": "customers",
        "persist": "false",
    }

    response = client.post("/api/v1/data/ingest/csv", data=data, files=files)
    assert response.status_code == 200
    res = response.json()
    assert res["success"] is True
    assert res["rows_read"] == 1
    assert res["rows_valid"] == 1
    assert res["rows_failed"] == 0
