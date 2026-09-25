"""Security and boundary safeguard tests for Phase 7 forecasting engine."""

import pytest
from app.agents.tools.models import ForecastMetricToolInput
from app.agents.tools.registry import ToolRegistry
from app.core.config import settings
from app.investigation.validators import CausalitySafeguard
from app.predictive.forecasting.explanation import ForecastExplainer
from app.predictive.schemas import (
    DataQualityStatus,
    EvaluationMetrics,
    ForecastDataQuality,
    ForecastPredictionPoint,
    ModelMetadata,
)
from pydantic import ValidationError


def test_forecast_tool_input_validation():
    """Verify ForecastMetricToolInput rejects invalid horizon or negative numbers."""
    with pytest.raises(ValidationError):
        ForecastMetricToolInput(
            target_metric="revenue",
            forecast_horizon=0,  # ge=1
        )

    with pytest.raises(ValidationError):
        ForecastMetricToolInput(
            target_metric="revenue",
            forecast_horizon=settings.MAX_FORECAST_HORIZON + 10,  # le=MAX_FORECAST_HORIZON
        )


def test_anti_prescriptive_safeguard_in_forecast_explanation():
    """Verify forecast explainer filters out prohibited prescriptive commands."""
    # Build dummy forecast result inputs
    preds = [
        ForecastPredictionPoint(
            period="2024-01-01",
            point_forecast=100.0,
            lower_bound=90.0,
            upper_bound=110.0,
        )
    ]
    model_meta = ModelMetadata(name="naive", version="1.0", selected=True)
    eval_metrics = EvaluationMetrics(mae=5.0, rmse=6.0, smape=4.0)
    data_quality = ForecastDataQuality(
        status=DataQualityStatus.READY,
        observation_count=12,
        frequency="monthly",
    )

    explainer = ForecastExplainer()
    explanation = explainer.explain(
        target_metric="revenue",
        frequency="monthly",
        model=model_meta,
        predictions=preds,
        evaluation=eval_metrics,
        data_quality=data_quality,
        explanation_level="manager",
    )

    # Explanation must not contain prescriptive operational directives
    prohibited_directives = [
        "order 500 units",
        "raise prices",
        "reduce staff",
        "increase marketing spend",
        "purchase inventory",
    ]
    for directive in prohibited_directives:
        assert directive not in explanation.lower()

    # Verify CausalitySafeguard sanitizes raw text if prescriptive directive were introduced
    raw_prescriptive_text = "Forecast demand will rise. We should order 500 units and raise prices immediately."
    sanitized = CausalitySafeguard.sanitize_diagnostic_text(raw_prescriptive_text)
    assert "order 500 units" not in sanitized
    assert "raise prices" not in sanitized


def test_tool_registry_rejects_unregistered_predictive_tools():
    """Verify ToolRegistry rejects unauthorized tool executions."""
    with pytest.raises(KeyError, match="not registered"):
        ToolRegistry.get("execute_arbitrary_python_forecast")

    with pytest.raises(KeyError, match="not registered"):
        ToolRegistry.get("execute_arbitrary_sql_forecast")
