"""Integration tests for Agentic LangGraph workflow and ToolRegistry forecasting integration."""

from app.agents.service import NexusAgentService
from app.agents.tools.date_interpreter import DateInterpreter
from app.agents.tools.registry import ToolRegistry


def test_date_interpreter_prospective_queries():
    """Verify DateInterpreter parses prospective forecasting horizons."""
    parsed_3m = DateInterpreter.interpret("Forecast revenue for the next 3 months")
    assert parsed_3m.is_forecast is True
    assert parsed_3m.forecast_horizon == 3

    parsed_1m = DateInterpreter.interpret("What will sales be next month?")
    assert parsed_1m.is_forecast is True
    assert parsed_1m.forecast_horizon == 1

    parsed_q = DateInterpreter.interpret("Expected order volume next quarter")
    assert parsed_q.is_forecast is True
    assert parsed_q.forecast_horizon == 3


def test_tool_registry_has_forecast_metric():
    """Verify forecast_metric tool is registered in ToolRegistry."""
    tool = ToolRegistry.get("forecast_metric")
    assert tool is not None
    assert tool.name == "forecast_metric"
    assert "target_metric" in tool.parameters_schema["properties"]


def test_agent_workflow_routes_to_forecasting(predictive_db_session):
    """Verify natural language forecast query executes through NexusAgentService with forecast_summary."""
    service = NexusAgentService(predictive_db_session)
    response = service.run_analysis(
        query="Forecast revenue for the next 3 months",
        explanation_level="manager",
    )

    assert response.status == "completed"
    assert response.forecast_summary is not None
    assert "predictions" in response.forecast_summary
    assert len(response.forecast_summary["predictions"]) == 3
    assert "forecast" in response.answer.lower() or "prediction" in response.answer.lower()


def test_agent_workflow_preserves_simple_analytics(multi_period_db):
    """Verify standard historical query does not route to forecasting."""
    from datetime import date
    service = NexusAgentService(multi_period_db)
    response = service.run_analysis(
        query="What was our revenue in August 2024?",
        explanation_level="manager",
        reference_date=date(2024, 9, 1),
    )

    assert response.status == "completed"
    assert response.forecast_summary is None

