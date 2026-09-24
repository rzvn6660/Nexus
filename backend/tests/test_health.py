"""Tests for NEXUS health and root system endpoints."""

from fastapi.testclient import TestClient


def test_root_endpoint(client: TestClient) -> None:
    """Validate root landing endpoint returns platform metadata."""
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "NEXUS"
    assert "Agentic Business Intelligence Platform" in data["title"]
    assert data["tagline"] == "Where Business Data Becomes Intelligence."
    assert data["health"] == "/api/health"


def test_api_health_endpoint(client: TestClient) -> None:
    """Validate /api/health endpoint structure and mandatory fields."""
    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()

    # Core required fields
    assert data["status"] == "healthy"
    assert data["service"] == "nexus"
    assert "version" in data
    assert "environment" in data
    assert "timestamp" in data

    # Correlation header check
    assert "X-Request-ID" in response.headers
    assert "X-Process-Time-Ms" in response.headers


def test_api_v1_health_endpoint(client: TestClient) -> None:
    """Validate versioned /api/v1/health endpoint produces identical contract."""
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["service"] == "nexus"
