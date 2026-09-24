"""Specialized handling nodes for unsupported domains and ambiguous queries."""

from typing import Any

from app.agents.state.models import AgentState


def handle_unsupported_node(state: AgentState) -> dict[str, Any]:
    """
    Politely reject non-business or out-of-scope requests while guiding user back
    to supported deterministic capabilities.
    """
    reason = state.get("unsupported_reason") or (
        "NEXUS is an agentic business intelligence platform specialized in deterministic analytics, "
        "financial metrics, customer insights, inventory management, and variance diagnostics."
    )
    message = (
        f"{reason}\n\n"
        "Supported capabilities include:\n"
        "• Financial metrics & period comparisons (Revenue, Profit, Margins, AOV, COGS)\n"
        "• Sales timeseries & trends (daily, weekly, monthly, quarterly)\n"
        "• Product & category rankings\n"
        "• Customer RFM quintiles, cohort retention, and repeat purchase patterns\n"
        "• Inventory health, valuation, turnover, and SKU velocity\n"
        "• Revenue variance diagnosis and Price/Volume/Mix decomposition\n"
        "• Statistical correlation and hypothesis testing"
    )

    return {
        "final_answer": message,
        "follow_up_questions": [
            "What was our revenue last month?",
            "Which products generated the highest revenue?",
            "What is our current inventory valuation?",
        ],
    }


def handle_clarification_node(state: AgentState) -> dict[str, Any]:
    """
    Prompt user for specific parameters when a query is too ambiguous to produce a defensible answer.
    """
    question = state.get("clarification_question") or (
        "Could you please clarify the specific timeframe or metric you would like to analyze?"
    )

    return {
        "final_answer": question,
        "follow_up_questions": [
            "Analyze revenue for the current month",
            "Analyze revenue for the past 30 days",
            "Show all-time financial summary",
        ],
    }
