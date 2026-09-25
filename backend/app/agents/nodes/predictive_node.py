"""LangGraph node executing deterministic time-series forecasting via ForecastingService."""

from datetime import date
from typing import Any
from langchain_core.runnables import RunnableConfig
from sqlalchemy.orm import Session

from app.agents.state.models import AgentState
from app.predictive.schemas import ForecastRequest, ModelPolicy
from app.predictive.services.forecasting_service import ForecastingService


def execute_forecast_node(
    state: AgentState, config: RunnableConfig | None = None
) -> dict[str, Any]:
    """Execute deterministic forecasting for queries classified as predictive."""
    configurable = config.get("configurable", {}) if config else {}
    session: Session = configurable.get("session") or configurable.get("db_session")
    if not session:
        return {
            "errors": ["Database session unavailable for predictive execution."],
            "is_unsupported": True,
        }

    query = state.get("user_query", "")
    resolved_dates = state.get("resolved_dates", {})
    semantic_ctx = state.get("semantic_context")

    target = "revenue"
    if state.get("forecast_target"):
        target = state["forecast_target"]
    elif semantic_ctx and semantic_ctx.get("canonical_name"):
        target = semantic_ctx["canonical_name"]

    horizon = 3
    if state.get("forecast_horizon"):
        horizon = state["forecast_horizon"]
    elif resolved_dates.get("forecast_horizon"):
        horizon = resolved_dates["forecast_horizon"]

    frequency = state.get("forecast_frequency") or resolved_dates.get("granularity") or "monthly"

    ref_date = None
    if state.get("reference_date"):
        try:
            ref_date = date.fromisoformat(state["reference_date"])
        except (ValueError, TypeError):
            ref_date = None

    req = ForecastRequest(
        query=query,
        target_metric=target,
        forecast_horizon=horizon,
        frequency=frequency,
        model_policy=ModelPolicy.VALIDATED_BEST,
        explanation_level=state.get("explanation_level", "manager"),
        reference_date=ref_date,
    )

    svc = ForecastingService(session)
    result = svc.forecast(req)

    tools_used = list(state.get("tools_used", []))
    if "forecast_metric" not in tools_used:
        tools_used.append("forecast_metric")

    return {
        "forecast_result": result.model_dump(mode="json"),
        "final_answer": result.explanation,
        "tools_used": sorted(set(tools_used)),
        "assumptions": result.assumptions,
        "limitations": result.limitations,
        "evidence": [result.evidence.model_dump(mode="json")],
        "follow_up_questions": [
            "Would you like to forecast demand for a specific product SKU?",
            "Should we inspect different backtesting horizons?",
            "Would you like to examine the sensitivity of these forecast intervals?",
        ],
    }
