"""Tests for deterministic tool registry and tool execution."""

from app.agents.tools.registry import tool_registry
from sqlalchemy.orm import Session


def test_tool_registry_has_all_phase3_tools() -> None:
    expected_tools = [
        "get_financial_summary",
        "get_sales_timeseries",
        "get_product_rankings",
        "get_category_breakdown",
        "get_customer_segments",
        "get_rfm_analysis",
        "get_cohort_analysis",
        "get_repeat_purchase",
        "get_inventory_overview",
        "get_inventory_turnover",
        "get_inventory_velocity",
        "get_expense_analytics",
        "run_variance_analysis",
        "run_price_volume_mix",
        "run_correlation",
        "run_hypothesis_test",
    ]
    for t_name in expected_tools:
        assert tool_registry.has_tool(t_name), f"Missing registered tool: {t_name}"


def test_tool_registry_security_rejects_unregistered(multi_period_db: Session) -> None:
    result = tool_registry.execute(
        "drop_database_tables",
        multi_period_db,
        {"sql": "DROP TABLE sales;"},
    )
    assert result.status == "error"
    assert "Security violation" in result.error_message


def test_tool_execution_financial_summary(multi_period_db: Session) -> None:
    result = tool_registry.execute(
        "get_financial_summary",
        multi_period_db,
        {
            "date_from": "2024-08-01",
            "date_to": "2024-08-31",
            "comparison_date_from": "2024-07-01",
            "comparison_date_to": "2024-07-31",
        },
    )
    assert result.status == "success"
    assert result.result is not None
    assert "net_sales" in result.result
    assert result.evidence is not None
    assert result.evidence.get("metric") == "financial_summary"
    assert len(result.assumptions) > 0


def test_tool_execution_product_rankings(multi_period_db: Session) -> None:
    result = tool_registry.execute(
        "get_product_rankings",
        multi_period_db,
        {
            "date_from": "2024-08-01",
            "date_to": "2024-08-31",
            "ranking_metric": "revenue",
            "limit": 5,
        },
    )
    assert result.status == "success"
    assert "items" in result.result
    assert len(result.result["items"]) <= 5


def test_tool_execution_variance_analysis(multi_period_db: Session) -> None:
    result = tool_registry.execute(
        "run_variance_analysis",
        multi_period_db,
        {
            "date_from": "2024-08-01",
            "date_to": "2024-08-31",
            "comparison_date_from": "2024-07-01",
            "comparison_date_to": "2024-07-31",
            "dimension": "category",
        },
    )
    assert result.status == "success"
    assert "total_variance" in result.result
    assert "top_positive_contributors" in result.result


def test_tool_execution_pvm_decomposition(multi_period_db: Session) -> None:
    result = tool_registry.execute(
        "run_price_volume_mix",
        multi_period_db,
        {
            "date_from": "2024-08-01",
            "date_to": "2024-08-31",
            "comparison_date_from": "2024-07-01",
            "comparison_date_to": "2024-07-31",
        },
    )
    assert result.status == "success"
    assert result.result.get("reconciled") is True
