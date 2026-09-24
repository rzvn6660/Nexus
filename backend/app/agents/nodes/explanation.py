"""Explanation synthesis node generating grounded, non-hallucinated analytical narratives."""

from typing import Any

from app.agents.providers.factory import get_llm_provider
from app.agents.state.models import AgentState, AnalysisPlan, ExplanationLevel


def generate_explanation_node(state: AgentState) -> dict[str, Any]:
    """
    Synthesize natural language explanation grounded strictly in the executed tools and evidence.
    Generates intelligent follow-up suggestions for analyst and business user workflows.
    """
    errors = state.get("errors", [])
    tool_results = state.get("tool_results", [])
    evidence = state.get("evidence", [])
    user_query = state.get("user_query", "")

    # If critical errors occurred and no tools succeeded
    if errors and not any(r.get("status") == "success" for r in tool_results):
        err_text = "\n".join(errors)
        return {
            "final_answer": (
                "I was unable to complete the requested analysis due to the following issue(s):\n"
                f"{err_text}\n\n"
                "Please verify the requested timeframe, metrics, and parameters."
            ),
            "follow_up_questions": [
                "Would you like to try a different date range?",
                "Would you like an overview of overall business summary metrics instead?",
            ],
        }

    exp_lvl_str = state.get("explanation_level", "manager")
    try:
        exp_lvl = ExplanationLevel(exp_lvl_str)
    except ValueError:
        exp_lvl = ExplanationLevel.MANAGER

    plan_dict = state.get("analysis_plan")
    plan = AnalysisPlan.model_validate(plan_dict) if plan_dict else None

    provider = get_llm_provider()
    explanation = provider.explain_results(
        query=user_query,
        plan=plan,
        tool_results=tool_results,
        evidence=evidence,
        explanation_level=exp_lvl,
    )

    # Generate contextual follow-up questions
    follow_ups: list[str] = []
    tools_used = state.get("tools_used", [])

    if "get_financial_summary" in tools_used:
        follow_ups.append("Would you like to see which products or categories contributed most to this revenue?")
        follow_ups.append("Should we inspect monthly revenue trend over the past 6 months?")
    elif "run_variance_analysis" in tools_used:
        follow_ups.append("Would you like to run a Price/Volume/Mix decomposition on this change?")
        follow_ups.append("Should we analyze customer segment retention during this interval?")
    elif "get_product_rankings" in tools_used:
        follow_ups.append("Would you like to check inventory stock and turnover for these top products?")
        follow_ups.append("Should we examine product profit margins and unit cost breakdowns?")
    elif "get_inventory_overview" in tools_used:
        follow_ups.append("Would you like to identify slow-moving or dormant inventory items?")
        follow_ups.append("Should we review the inventory turnover ratio and DSI for the period?")
    else:
        follow_ups.append("Would you like to compare these figures with the previous period?")
        follow_ups.append("Should we generate a visual timeseries breakdown?")

    return {
        "final_answer": explanation,
        "follow_up_questions": follow_ups,
    }
