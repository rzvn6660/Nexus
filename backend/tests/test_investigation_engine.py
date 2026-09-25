"""Integration tests for Phase 6 InvestigationEngine and API endpoint."""

from datetime import date

from app.investigation.engine import InvestigationEngine
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session


def test_investigation_engine_end_to_end_revenue_decline(multi_period_db: Session):
    """Verify full multi-step diagnostic investigation against multi-period test database."""
    engine = InvestigationEngine(multi_period_db)
    ref = date(2023, 8, 1)

    response = engine.investigate(
        query="Why did revenue decline in July 2023?",
        explanation_level="manager",
        reference_date=ref,
    )

    assert response.status == "completed"
    assert response.investigation_type == "revenue_decline"
    assert len(response.investigation_steps) >= 3
    assert len(response.observations) >= 2
    assert len(response.conclusions) >= 1
    assert len(response.evidence) >= 2
    assert len(response.tools_used) >= 2
    assert "get_financial_summary" in response.tools_used
    assert "run_variance_analysis" in response.tools_used
    assert "run_price_volume_mix" in response.tools_used

    # Verify structured sections in narrative
    assert "### What happened" in response.explanation
    assert "### Main contributors" in response.explanation
    assert "### What the data does not establish" in response.explanation
    assert "### Evidence gaps" in response.explanation
    assert len(response.evidence_gaps) > 0


def test_investigation_engine_clarification_on_ambiguous_term(multi_period_db: Session):
    """Verify semantic ambiguity stops investigation cleanly and requests clarification."""
    engine = InvestigationEngine(multi_period_db)
    response = engine.investigate(
        query="Why did our turnover fall?",
        explanation_level="manager",
    )

    assert response.status == "clarification_needed"
    assert response.stopped_reason == "terminology_ambiguity"
    assert "clarify" in response.explanation.lower() or "mean" in response.explanation.lower()


def test_investigation_api_endpoint(client: TestClient, multi_period_db: Session):
    """Verify POST /api/v1/investigation/analyze returns compliant InvestigationResponse."""
    payload = {
        "query": "Why did revenue drop in July 2023?",
        "explanation_level": "manager",
        "reference_date": "2023-08-01",
    }

    res = client.post("/api/v1/investigation/analyze", json=payload)
    assert res.status_code == 200

    data = res.json()
    assert data["status"] == "completed"
    assert data["investigation_type"] == "revenue_decline"
    assert len(data["investigation_steps"]) >= 3
    assert len(data["observations"]) >= 1
    assert len(data["conclusions"]) >= 1
    assert "### What happened" in data["explanation"]
    assert "### Main contributors" in data["explanation"]


def test_investigation_profit_decline_strategy(multi_period_db: Session):
    """Verify profit decline investigation executes expense and PVM analytics."""
    engine = InvestigationEngine(multi_period_db)
    ref = date(2024, 9, 1)

    response = engine.investigate(
        query="Why did net profit decrease last month?",
        explanation_level="manager",
        reference_date=ref,
    )

    assert response.status == "completed"
    assert response.investigation_type == "profit_decline"
    assert "get_financial_summary" in response.tools_used
    assert "get_expense_analytics" in response.tools_used
    assert len(response.evidence) >= 2
