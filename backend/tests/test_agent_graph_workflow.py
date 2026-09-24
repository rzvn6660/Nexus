"""Integration tests for the LangGraph workflow and NexusAgentService."""

from datetime import date

from app.agents.service import NexusAgentService
from sqlalchemy.orm import Session


def test_agent_workflow_single_tool_revenue_lookup(multi_period_db: Session) -> None:
    service = NexusAgentService(multi_period_db)
    ref = date(2024, 9, 1)

    response = service.run_analysis(
        query="What was our revenue in August 2024?",
        explanation_level="manager",
        reference_date=ref,
    )

    assert response.status == "completed"
    assert response.intent == "metric_lookup"
    assert "get_financial_summary" in response.tools_used
    assert len(response.evidence) > 0
    assert response.evidence[0].metric == "financial_summary"
    assert len(response.answer) > 0
    assert "Net Revenue" in response.answer or "Revenue" in response.answer
    assert response.execution_metadata.tool_call_count >= 1


def test_agent_workflow_multi_step_diagnostic(multi_period_db: Session) -> None:
    service = NexusAgentService(multi_period_db)
    ref = date(2024, 9, 1)

    response = service.run_analysis(
        query="Why did revenue change and which category contributed most?",
        explanation_level="analyst",
        reference_date=ref,
    )

    assert response.status == "completed"
    assert response.intent == "diagnostic_analysis"
    assert "get_financial_summary" in response.tools_used
    assert "run_variance_analysis" in response.tools_used
    assert len(response.evidence) >= 2
    assert "Traceability & Evidence" in response.answer
    assert response.execution_metadata.iterations >= 2


def test_agent_workflow_unsupported_request(multi_period_db: Session) -> None:
    service = NexusAgentService(multi_period_db)

    response = service.run_analysis(
        query="Can you tell me a joke about finance?",
        explanation_level="simple",
    )

    assert response.status == "unsupported"
    assert response.intent == "unsupported"
    assert len(response.tools_used) == 0
    assert "NEXUS is an agentic business intelligence platform" in response.answer


def test_agent_workflow_clarification_path(multi_period_db: Session) -> None:
    service = NexusAgentService(multi_period_db)

    response = service.run_analysis(
        query="   ",
        explanation_level="manager",
    )

    assert response.status == "clarification_needed"
    assert response.needs_clarification is True
    assert response.clarification_prompt is not None


def test_agent_workflow_inventory_overview(multi_period_db: Session) -> None:
    service = NexusAgentService(multi_period_db)

    response = service.run_analysis(
        query="What is our current inventory valuation and stock status?",
        explanation_level="manager",
    )

    assert response.status == "completed"
    assert response.intent == "inventory_analysis"
    assert "get_inventory_overview" in response.tools_used
    assert "inventory valuation" in response.answer.lower()
