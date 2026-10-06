"""Request understanding and intent classification node."""

from datetime import date
from typing import Any

from app.agents.providers.factory import get_llm_provider
from app.agents.state.models import AgentState, IntentCategory, IntentResult
from app.agents.tools.date_interpreter import DateInterpreter
from app.decisions.gateway import get_decision_gateway


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

    # Check for underspecified requests asking for breakdowns/drilldowns without metric or dimension
    import re
    q_clean = re.sub(r"[^\w\s]", "", user_query.lower()).strip()
    generic_breakdown_phrases = [
        "give me a breakdown",
        "show me a breakdown",
        "provide a breakdown",
        "breakdown please",
        "run a breakdown",
        "breakdown",
        "give a breakdown",
        "break it down",
        "drill down",
        "give me a decomposition",
    ]
    if any(q_clean == p or q_clean.startswith(p + " ") or q_clean.endswith(" " + p) for p in generic_breakdown_phrases):
        metric_tokens = ["revenue", "sales", "profit", "margin", "order", "orders", "unit", "units", "cogs", "expense", "inventory", "turnover", "customer"]
        dim_tokens = ["category", "product", "sku", "brand", "segment", "channel", "month", "quarter", "year", "region", "store"]
        has_metric = any(m in q_clean for m in metric_tokens)
        has_dim = any(d in q_clean for d in dim_tokens)
        if not (has_metric and has_dim):
            return {
                "intent": {"category": "ambiguous", "confidence": 1.0, "reasoning": "Query requests a breakdown without specifying metric and dimension."},
                "resolved_dates": resolved_dates,
                "needs_clarification": True,
                "clarification_question": "Please specify which metric you would like to break down (e.g., revenue, gross profit, or order volume) and across which dimension (e.g., product category, customer segment, or monthly timeframe).",
                "evidence_status": "INSUFFICIENT",
                "is_unsupported": False,
            }

    # Check for business profile query
    from app.decisions.taxonomy import get_canonical_intent_ids, is_business_profile_query, resolve_intent
    if is_business_profile_query(user_query):
        intent_result = IntentResult(
            category=IntentCategory.BUSINESS_PROFILE,
            subtype="business_profile",
            confidence=1.0,
            reasoning="Query requests active tenant business workspace profile metadata.",
        )
        return {
            "intent": intent_result.model_dump(),
            "resolved_dates": resolved_dates,
            "is_unsupported": False,
            "evidence_status": "INSUFFICIENT",
        }

    # Intent classification via Decision Gateway
    gateway = get_decision_gateway()
    supported_intents = get_canonical_intent_ids()
    decision = gateway.route_intent(
        user_query,
        supported_intents,
        metadata={"request_id": state.get("request_id")},
    )

    raw_decision_str = decision.decision or IntentCategory.METRIC_LOOKUP.value
    canonical_id, subtype = resolve_intent(raw_decision_str)
    try:
        intent_cat = IntentCategory(canonical_id)
    except ValueError:
        intent_cat = IntentCategory.METRIC_LOOKUP

    intent_result = IntentResult(
        category=intent_cat,
        subtype=subtype,
        confidence=decision.confidence if decision.confidence is not None else 1.0,
        reasoning=decision.rationale or "Classified by Decision Gateway",
    )

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
