"""Tests for the agent API endpoint POST /api/v1/agent/analyze."""

from app.core.database import get_db
from app.main import app
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session


def test_api_agent_analyze_revenue_lookup(multi_period_db: Session) -> None:
    def override_get_db():
        try:
            yield multi_period_db
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)

    try:
        payload = {
            "query": "What was our revenue in August 2024?",
            "explanation_level": "manager",
            "reference_date": "2024-09-01",
        }
        response = client.post("/api/v1/agent/analyze", json=payload)
        assert response.status_code == 200
        data = response.json()

        assert data["status"] == "completed"
        assert data["intent"] == "metric_lookup"
        assert "get_financial_summary" in data["tools_used"]
        assert len(data["evidence"]) > 0
        assert data["evidence"][0]["source_tables"] == ["sales", "sale_items", "products", "expenses"]
        assert "execution_metadata" in data
        assert data["execution_metadata"]["elapsed_ms"] > 0
    finally:
        app.dependency_overrides.clear()


def test_api_agent_analyze_diagnostic_variance(multi_period_db: Session) -> None:
    def override_get_db():
        try:
            yield multi_period_db
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)

    try:
        payload = {
            "query": "Why did revenue change and which product contributed most?",
            "explanation_level": "analyst",
            "reference_date": "2024-09-01",
        }
        response = client.post("/api/v1/agent/analyze", json=payload)
        assert response.status_code == 200
        data = response.json()

        assert data["status"] == "completed"
        assert data["intent"] == "diagnostic_analysis"
        assert "run_variance_analysis" in data["tools_used"]
        assert "Traceability & Evidence" in data["answer"]
    finally:
        app.dependency_overrides.clear()


def test_api_agent_analyze_unsupported(multi_period_db: Session) -> None:
    def override_get_db():
        try:
            yield multi_period_db
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)

    try:
        payload = {
            "query": "What will the weather be like tomorrow?",
            "explanation_level": "simple",
        }
        response = client.post("/api/v1/agent/analyze", json=payload)
        assert response.status_code == 200
        data = response.json()

        assert data["status"] == "unsupported"
        assert data["intent"] == "unsupported"
        assert len(data["tools_used"]) == 0
    finally:
        app.dependency_overrides.clear()


def test_api_agent_analyze_explanation_levels(multi_period_db: Session) -> None:
    def override_get_db():
        try:
            yield multi_period_db
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)

    try:
        for lvl in ["simple", "manager", "technical"]:
            payload = {
                "query": "What are our top products by revenue?",
                "explanation_level": lvl,
                "reference_date": "2024-09-01",
            }
            response = client.post("/api/v1/agent/analyze", json=payload)
            assert response.status_code == 200
            data = response.json()
            assert data["explanation_level"] == lvl
            assert len(data["answer"]) > 0
    finally:
        app.dependency_overrides.clear()
