"""Tests for agent state, intent classification, and structured planning."""

from app.agents.nodes.planning import validate_plan_node
from app.agents.providers.mock import MockLLMProvider
from app.agents.state.models import (
    AgentState,
    IntentCategory,
)
from app.agents.tools.registry import tool_registry


def test_intent_classification_categories() -> None:
    provider = MockLLMProvider()
    supported = [e.value for e in IntentCategory]

    # Metric lookup
    res = provider.classify_intent("What was our gross revenue?", supported)
    assert res.category == IntentCategory.METRIC_LOOKUP

    # Comparison
    res = provider.classify_intent("How did revenue change compared to last month?", supported)
    assert res.category == IntentCategory.COMPARISON

    # Trend
    res = provider.classify_intent("Show me the monthly sales trend over time", supported)
    assert res.category == IntentCategory.TREND

    # Product
    res = provider.classify_intent("Which are our best selling products by revenue?", supported)
    assert res.category == IntentCategory.PRODUCT_ANALYSIS

    # Customer
    res = provider.classify_intent("Calculate customer RFM scores and segments", supported)
    assert res.category == IntentCategory.CUSTOMER_ANALYSIS

    # Inventory
    res = provider.classify_intent("What is our current inventory valuation and stock count?", supported)
    assert res.category == IntentCategory.INVENTORY_ANALYSIS

    # Expense
    res = provider.classify_intent("What were our operating expenses and recurring overhead?", supported)
    assert res.category == IntentCategory.EXPENSE_ANALYSIS

    # Diagnostic
    res = provider.classify_intent("Why did revenue decline and which products contributed most?", supported)
    assert res.category == IntentCategory.DIAGNOSTIC_ANALYSIS

    # Statistical
    res = provider.classify_intent("Is there a statistically significant correlation between quantity and discount?", supported)
    assert res.category == IntentCategory.STATISTICAL_ANALYSIS

    # Unsupported
    res = provider.classify_intent("Can you write a poem about sales?", supported)
    assert res.category == IntentCategory.UNSUPPORTED


def test_plan_generation_multi_step_diagnostic() -> None:
    provider = MockLLMProvider()
    tools = tool_registry.list_tools()
    dates = {
        "date_from": "2024-08-01",
        "date_to": "2024-08-31",
        "comparison_date_from": "2024-07-01",
        "comparison_date_to": "2024-07-31",
    }
    plan = provider.create_plan(
        query="Why did revenue change and which product contributed most?",
        intent=IntentCategory.DIAGNOSTIC_ANALYSIS,
        available_tools=tools,
        resolved_dates=dates,
    )
    assert len(plan.steps) == 2
    assert plan.steps[0].tool_name == "get_financial_summary"
    assert plan.steps[1].tool_name == "run_variance_analysis"
    assert plan.steps[1].arguments.get("dimension") == "product"


def test_plan_validation_valid_plan() -> None:
    valid_state: AgentState = {
        "analysis_plan": {
            "goal": "Test goal",
            "steps": [
                {
                    "step_index": 0,
                    "tool_name": "get_financial_summary",
                    "purpose": "Test summary",
                    "arguments": {"date_from": "2024-08-01", "date_to": "2024-08-31"},
                }
            ],
            "context_dates": {},
        },
        "errors": [],
    }
    res = validate_plan_node(valid_state)
    assert len(res.get("errors", [])) == 0


def test_plan_validation_rejects_unregistered_tool() -> None:
    invalid_state: AgentState = {
        "analysis_plan": {
            "goal": "Malicious goal",
            "steps": [
                {
                    "step_index": 0,
                    "tool_name": "arbitrary_sql_executor",
                    "purpose": "Security breach attempt",
                    "arguments": {"query": "SELECT * FROM users"},
                }
            ],
            "context_dates": {},
        },
        "errors": [],
    }
    res = validate_plan_node(invalid_state)
    assert res.get("evidence_status") == "ERROR"
    assert any("not in registry" in err for err in res.get("errors", []))
