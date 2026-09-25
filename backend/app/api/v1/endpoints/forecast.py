"""API endpoints for Phase 7 Predictive Intelligence & Forecasting."""

import re

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.agents.tools.date_interpreter import DateInterpreter
from app.core.config import settings
from app.core.database import get_db
from app.predictive.schemas import (
    ForecastAnalyzeRequest,
    ForecastFrequency,
    ForecastRequest,
    ForecastResponse,
    ForecastTarget,
    ModelPolicy,
    forecast_result_to_response,
)
from app.predictive.services.forecasting_service import ForecastingService

router = APIRouter()


def _resolve_forecast_intent_from_query(query: str) -> tuple[str, str, int, str | None, str | None]:
    """
    Deterministically resolve target metric, frequency, horizon, and entity from text.
    Returns (target_metric, frequency, horizon, entity_type, entity_id).
    """
    q = query.lower()
    
    # 1. Target metric resolution
    if any(k in q for k in ["demand", "product demand"]):
        target = "product_demand"
    elif any(k in q for k in ["unit", "volume", "units sold"]):
        target = "units"
    elif any(k in q for k in ["order", "orders", "order count"]):
        target = "orders"
    elif any(k in q for k in ["sale", "sales"]):
        target = "sales"
    else:
        target = "revenue"

    # 2. Date and horizon interpretation
    parsed_date = DateInterpreter.interpret(query)
    horizon = parsed_date.forecast_horizon if (parsed_date.is_forecast and parsed_date.forecast_horizon) else 3
    
    if "day" in q or "daily" in q:
        frequency = "daily"
    elif "week" in q or "weekly" in q:
        frequency = "weekly"
    else:
        frequency = "monthly"

    # 3. Entity extraction (e.g. 'Product A', 'SKU-001')
    entity_type = None
    entity_id = None
    product_match = re.search(r"\b(?:product|sku)\s+([a-zA-Z0-9_\-]+)\b", q, re.IGNORECASE)
    if product_match:
        entity_type = "product"
        entity_id = product_match.group(1).upper()
        if target == "revenue":
            target = "product_demand"

    return target, frequency, horizon, entity_type, entity_id


@router.post(
    "/analyze",
    response_model=ForecastResponse,
    status_code=status.HTTP_200_OK,
    summary="Analyze natural language forecast query",
    description=(
        "Processes a natural language forecasting question, resolves the canonical KPI "
        "and prospective horizon, validates time-series data quality, performs out-of-sample "
        "backtesting across baseline and statistical models, and produces a structured prediction "
        "with statistical prediction intervals and evidence."
    ),
)
def analyze_forecast_query(
    payload: ForecastAnalyzeRequest,
    db: Session = Depends(get_db),
) -> ForecastResponse:
    """Natural language entrypoint for predictive intelligence."""
    target_metric, frequency, horizon, entity_type, entity_id = _resolve_forecast_intent_from_query(payload.query)

    if horizon > settings.MAX_FORECAST_HORIZON:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Forecast horizon {horizon} exceeds maximum allowed limit of {settings.MAX_FORECAST_HORIZON} periods.",
        )

    service = ForecastingService(db)
    result = service.generate_forecast(
        target_metric=target_metric,
        frequency=frequency,
        forecast_horizon=horizon,
        entity_type=entity_type,
        entity_id=entity_id,
        model_policy="validated_best",
        explanation_level=payload.explanation_level,
        reference_date=payload.reference_date,
    )
    return forecast_result_to_response(result)


@router.post(
    "",
    response_model=ForecastResponse,
    status_code=status.HTTP_200_OK,
    summary="Generate structured time-series forecast",
    description=(
        "Generates a deterministic, backtested time-series forecast for a specific business metric "
        "and temporal frequency. Returns point predictions, prediction intervals, data quality status, "
        "and model provenance evidence."
    ),
)
def generate_structured_forecast(
    payload: ForecastRequest,
    db: Session = Depends(get_db),
) -> ForecastResponse:
    """Direct structured entrypoint for time-series forecasting."""
    if payload.forecast_horizon > settings.MAX_FORECAST_HORIZON:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Forecast horizon {payload.forecast_horizon} exceeds maximum allowed limit of {settings.MAX_FORECAST_HORIZON} periods.",
        )

    # Validate target metric
    valid_targets = [t.value for t in ForecastTarget]
    if payload.target_metric not in valid_targets:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid target metric '{payload.target_metric}'. Supported targets: {valid_targets}",
        )

    # Validate frequency
    valid_freqs = [f.value for f in ForecastFrequency]
    if payload.frequency not in valid_freqs:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid frequency '{payload.frequency}'. Supported frequencies: {valid_freqs}",
        )

    policy_str = payload.model_policy.value if isinstance(payload.model_policy, ModelPolicy) else str(payload.model_policy)

    service = ForecastingService(db)
    result = service.generate_forecast(
        target_metric=payload.target_metric,
        frequency=payload.frequency,
        forecast_horizon=payload.forecast_horizon,
        entity_type=payload.entity_type,
        entity_id=payload.entity_id,
        model_policy=policy_str,
        specific_model=payload.specific_model,
        confidence_level=payload.confidence_level,
        explanation_level=payload.explanation_level,
        reference_date=payload.reference_date,
    )
    return forecast_result_to_response(result)
