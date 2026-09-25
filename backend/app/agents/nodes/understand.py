"""Request understanding and intent classification node."""

from datetime import date
from typing import Any

from app.agents.providers.factory import get_llm_provider
from app.agents.state.models import AgentState, IntentCategory
from app.agents.tools.date_interpreter import DateInterpreter


def understand_request_node(state: AgentState) -> dict[str, Any]:
    """
    Classify query intent, resolve temporal boundaries, and detect out-of-scope or ambiguous requests.
    """
    user_query = state.get("user_query", "").strip()
    if not user_query:
        return {
            "needs_clarification": True,
            "clarification_question": "Please provide a business analytics question or metric to analyze.",
            "evidence_status": "INSUFFICIENT",
        }

    # Deterministic date resolution
    ref_date_str = state.get("reference_date")
    ref_date = date.fromisoformat(ref_date_str) if ref_date_str else None
    resolved_dates = DateInterpreter.interpret(user_query, reference_date=ref_date)

    # Intent classification via LLM provider
    provider = get_llm_provider()
    supported_intents = [e.value for e in IntentCategory]
    intent_result = provider.classify_intent(user_query, supported_intents)

    # Check for unsupported request
    if intent_result.category == IntentCategory.UNSUPPORTED:
        return {
            "intent": intent_result.model_dump(),
            "resolved_dates": resolved_dates,
            "is_unsupported": True,
            "unsupported_reason": (
                "NEXUS is an agentic business intelligence platform specialized in deterministic analytics, "
                "factual financial calculations, product performance, customer metrics, inventory tracking, "
                "diagnostics, and time-series forecasting. Generic chit-chat, automated actions, and speculative decisions "
                "are outside the current analytical engine boundary."
            ),
            "evidence_status": "INSUFFICIENT",
        }

    # Check if dates or query is severely ambiguous for a time-dependent metric
    if resolved_dates.get("is_ambiguous"):
        return {
            "intent": intent_result.model_dump(),
            "resolved_dates": resolved_dates,
            "needs_clarification": True,
            "clarification_question": "Please specify the date range or timeframe you would like to analyze (e.g., 'last month', 'this quarter', or '2024-01-01 to 2024-06-30').",
            "evidence_status": "INSUFFICIENT",
        }

    is_forecast = (
        state.get("is_forecast_required", False)
        or intent_result.category == IntentCategory.FORECASTING
        or bool(resolved_dates.get("is_forecast"))
    )

    return {
        "intent": intent_result.model_dump(),
        "resolved_dates": resolved_dates,
        "is_forecast_required": is_forecast,
        "needs_clarification": False,
        "is_unsupported": False,
    }
