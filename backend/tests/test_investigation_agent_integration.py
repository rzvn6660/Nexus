"""Integration tests for LangGraph Agent and Investigation Engine interactions."""

from datetime import date

from app.agents.service import NexusAgentService
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session


def test_simple_metric_query_remains_simple_and_fast(multi_period_db: Session):
    """Verify descriptive queries do not launch the multi-step investigation engine."""
    service = NexusAgentService(multi_period_db)
    ref = date(2024, 9, 1)

    response = service.run_analysis(
        query="What was our net revenue in August 2024?",
        explanation_level="manager",
        reference_date=ref,
        is_investigation=False,
    )

    assert response.status == "completed"
    assert response.intent == "metric_lookup"
    assert len(response.tools_used) == 1
    assert "get_financial_summary" in response.tools_used
    assert response.diagnostic_summary is None


def test_agent_with_investigation_flag_executes_diagnostic_flow(multi_period_db: Session):
    """Verify that setting is_investigation=True triggers the multi-step LangGraph investigation flow."""
    service = NexusAgentService(multi_period_db)
    ref = date(2024, 9, 1)

    response = service.run_analysis(
        query="Why did revenue decline in August 2024?",
        explanation_level="analyst",
        reference_date=ref,
        is_investigation=True,
    )

    assert response.status == "completed"
    assert response.diagnostic_summary is not None
    assert response.diagnostic_summary["investigation_type"] == "revenue_decline"
    assert len(response.tools_used) >= 2
    assert "get_financial_summary" in response.tools_used
    assert "run_variance_analysis" in response.tools_used
    assert "### What happened" in response.answer
    assert "### Main contributors" in response.answer


def test_agent_api_with_investigation_parameter(client: TestClient, multi_period_db: Session):
    """Verify POST /api/v1/agent/analyze works with is_investigation: true."""
    payload = {
        "query": "Why did gross margin fall in August 2024?",
        "explanation_level": "manager",
        "reference_date": "2024-09-01",
        "is_investigation": True,
    }

    res = client.post("/api/v1/agent/analyze", json=payload)
    assert res.status_code == 200

    data = res.json()
    assert data["status"] == "completed"
    assert data["diagnostic_summary"] is not None
    assert data["diagnostic_summary"]["investigation_type"] == "margin_change"
    assert len(data["tools_used"]) >= 2
