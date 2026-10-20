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


def test_agent_api_with_investigation_parameter(authenticated_client: TestClient, multi_period_db: Session):
    """Verify POST /api/v1/agent/analyze works with is_investigation: true."""
    payload = {
        "query": "Why did gross margin fall in August 2024?",
        "explanation_level": "manager",
        "reference_date": "2024-09-01",
        "is_investigation": True,
    }

    res = authenticated_client.post("/api/v1/agent/analyze", json=payload)
    assert res.status_code == 200

    data = res.json()
    assert data["status"] == "completed"
    assert data["diagnostic_summary"] is not None
    assert data["diagnostic_summary"]["investigation_type"] == "margin_change"
    assert len(data["tools_used"]) >= 2


def test_investigation_node_extract_observations_with_comparison_percentage():
    """Regression test: verify _extract_observations correctly formats baseline comparison and percentage change without NameError."""
    from app.agents.nodes.investigation_node import _extract_observations
    from app.investigation.models import InvestigationPlan, InvestigationType

    plan = InvestigationPlan(
        goal="Diagnose revenue decline",
        investigation_type=InvestigationType.REVENUE_DECLINE,
        baseline_dates={"date_from": "2024-07-01"},
        comparison_dates={"date_from": "2024-08-01"},
        steps=[],
    )

    # 1. Negative comparison percentage
    result_neg = {
        "currency": "USD",
        "currency_symbol": "$",
        "net_sales": {
            "value": 185000.0,
            "comparison_value": 220000.0,
            "percentage_change": -15.9,
            "formatted": "$185,000.00",
        },
    }
    obs_neg = _extract_observations(1, "get_financial_summary", result_neg, plan)
    assert len(obs_neg) == 1
    assert obs_neg[0].metric == "net_sales"
    assert obs_neg[0].value_current == 185000.0
    assert obs_neg[0].value_baseline == 220000.0
    assert obs_neg[0].change_pct == -15.9
    assert "$185,000.00" in obs_neg[0].statement
    assert "compared to $220,000.00 in the baseline comparison period (-15.9%)." in obs_neg[0].statement

    # 2. Positive comparison percentage
    result_pos = {
        "currency": "INR",
        "currency_symbol": "₹",
        "net_sales": {
            "value": 225000.0,
            "comparison_value": 200000.0,
            "percentage_change": 12.5,
            "formatted": "₹225,000.00",
        },
    }
    obs_pos = _extract_observations(2, "get_financial_summary", result_pos, plan)
    assert len(obs_pos) == 1
    assert "₹225,000.00" in obs_pos[0].statement
    assert "compared to ₹200,000.00 in the baseline comparison period (+12.5%)." in obs_pos[0].statement

    # 3. No baseline comparison
    result_no_comp = {
        "net_sales": {
            "value": 150000.0,
            "comparison_value": None,
            "percentage_change": None,
        },
    }
    obs_no_comp = _extract_observations(3, "get_financial_summary", result_no_comp, plan)
    assert len(obs_no_comp) == 1
    assert obs_no_comp[0].statement == "Net Sales (Revenue) was measured at $150,000.00."

    # 4. Baseline comparison present but percentage_change is None (e.g. baseline was 0.0)
    result_comp_no_pct = {
        "currency": "USD",
        "currency_symbol": "$",
        "net_sales": {
            "value": 50000.0,
            "comparison_value": 0.0,
            "percentage_change": None,
            "formatted": "$50,000.00",
        },
    }
    obs_comp_no_pct = _extract_observations(4, "get_financial_summary", result_comp_no_pct, plan)
    assert len(obs_comp_no_pct) == 1
    assert obs_comp_no_pct[0].change_pct is None
    assert obs_comp_no_pct[0].value_baseline == 0.0
    assert obs_comp_no_pct[0].value_current == 50000.0
    assert obs_comp_no_pct[0].statement == (
        "Net Sales (Revenue) was measured at $50,000.00 compared to $0.00 in the baseline comparison period."
    )
    assert "()" not in obs_comp_no_pct[0].statement


