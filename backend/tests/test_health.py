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
    assert data["liveness"] == "/api/health/live"
    assert data["readiness"] == "/api/health/ready"


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
    assert "dependency_status" in data

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


def test_api_health_live_endpoint(client: TestClient) -> None:
    """Validate liveness probe /api/health/live and /api/v1/health/live."""
    for path in ["/api/health/live", "/api/v1/health/live"]:
        response = client.get(path)
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "alive"
        assert "timestamp" in data


def test_api_health_ready_endpoint(client: TestClient) -> None:
    """Validate readiness probe /api/health/ready and /api/v1/health/ready."""
    for path in ["/api/health/ready", "/api/v1/health/ready"]:
        response = client.get(path)
        # In test environments without real PostgreSQL, readiness returns 503 or 200
        assert response.status_code in [200, 503]
        data = response.json()
        assert data["status"] in ["ready", "not_ready"]
        assert data["service"] == "nexus"
        assert "database" in data
