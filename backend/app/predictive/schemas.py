"""Strongly-typed schemas and domain models for Phase 7 Predictive Intelligence."""

from datetime import UTC, date, datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class ForecastTarget(str, Enum):
    """Supported forecasting target metrics."""
    REVENUE = "revenue"
    SALES = "sales"
    NET_REVENUE = "net_revenue"
    GROSS_SALES = "gross_sales"
    UNITS = "units"
    UNITS_SOLD = "units_sold"
    ORDERS = "orders"
    ORDER_VOLUME = "order_volume"
    PRODUCT_DEMAND = "product_demand"


class ForecastFrequency(str, Enum):
    """Supported chronological forecast frequencies."""
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"


class ModelPolicy(str, Enum):
    """Strategy for selecting the operational forecasting model."""
    VALIDATED_BEST = "validated_best"
    BASELINE_ONLY = "baseline_only"
    SPECIFIC_MODEL = "specific_model"


class DataQualityStatus(str, Enum):
    """Quality status of the historical training series."""
    READY = "ready"
    READY_WITH_WARNINGS = "ready_with_warnings"
    INSUFFICIENT_DATA = "insufficient_data"
    INVALID = "invalid"


class ForecastStatus(str, Enum):
    """Execution status of the forecasting operation."""
    COMPLETED = "completed"
    UNAVAILABLE = "unavailable"
    FAILED = "failed"


class ForecastDataQuality(BaseModel):
    """Structured assessment of historical time-series quality before model fitting."""
    status: DataQualityStatus
    observation_count: int = Field(..., description="Number of valid chronological observations.")
    frequency: str = Field(..., description="Inferred or requested frequency: daily, weekly, or monthly.")
    date_from: str | None = None
    date_to: str | None = None
    missing_periods: list[str] = Field(default_factory=list, description="Identified gap intervals.")
    missing_values: int = 0
    zero_periods_count: int = 0
    outliers_detected: int = 0
    warnings: list[str] = Field(default_factory=list)
    blocking_reasons: list[str] = Field(default_factory=list)


class ForecastPredictionPoint(BaseModel):
    """Single period point forecast with statistically derived prediction intervals."""
    period: str = Field(..., description="Chronological label, e.g. '2024-10' or '2024-10-15'.")
    period_start: str | None = Field(default=None, description="ISO datetime start of forecast interval.")
    period_end: str | None = Field(default=None, description="ISO datetime end of forecast interval.")
    point_forecast: float = Field(..., description="Expected central prediction value.")
    lower_bound: float = Field(..., description="Lower prediction interval limit at alpha.")
    upper_bound: float = Field(..., description="Upper prediction interval limit at alpha.")
    confidence_level: float = Field(default=0.95, description="Coverage probability for prediction intervals.")


class EvaluationMetrics(BaseModel):
    """Backtesting accuracy metrics computed strictly on out-of-sample validation windows."""
    mae: float = Field(..., description="Mean Absolute Error.")
    rmse: float = Field(..., description="Root Mean Squared Error.")
    mape: float | None = Field(None, description="Mean Absolute Percentage Error (handled safely for zeros).")
    smape: float = Field(..., description="Symmetric Mean Absolute Percentage Error (bounded 0-200%).")
    wape: float | None = Field(None, description="Weighted Absolute Percentage Error.")


class ModelMetadata(BaseModel):
    """Model registry record for candidate or selected forecasting model."""
    name: str = Field(..., description="Model identifier: naive, seasonal_naive, moving_average, exponential_smoothing, arima.")
    version: str = "1.0"
    model_type: str = Field(default="baseline", description="Category: baseline or statistical.")
    parameters: dict[str, Any] = Field(default_factory=dict)
    selection_reason: str | None = None
    is_baseline: bool = True
    selected: bool = Field(default=True, description="Whether this model was selected for the final forecast.")


class ForecastEvidence(BaseModel):
    """Audit record and provenance for a generated forecast, guaranteeing reproducibility."""
    forecast_id: str
    source_tables: list[str] = Field(default_factory=lambda: ["sales", "sale_items", "products"])
    source_columns: list[str] = Field(default_factory=lambda: ["transaction_date", "line_total", "quantity"])
    target_metric: str
    filters: dict[str, Any] = Field(default_factory=dict)
    training_range: dict[str, str | None]
    forecast_horizon: int
    frequency: str
    model: str
    model_parameters: dict[str, Any] = Field(default_factory=dict)
    validation_method: str = "expanding_window_backtest"
    validation_metrics: EvaluationMetrics
    selected_model_rationale: str
    assumptions: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    data_quality_status: str
    generated_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


class ForecastResult(BaseModel):
    """Structured result returned by the ForecastingService."""
    forecast_id: str
    status: ForecastStatus
    target_metric: str
    entity_type: str | None = None
    entity_id: str | None = None
    frequency: str
    training_period: dict[str, str | None]
    forecast_period: dict[str, str | None]
    model: ModelMetadata
    predictions: list[ForecastPredictionPoint] = Field(default_factory=list)
    evaluation: EvaluationMetrics
    data_quality: ForecastDataQuality
    evidence: ForecastEvidence
    assumptions: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    explanation: str
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


class ForecastRequest(BaseModel):
    """API request payload for generating deterministic time-series forecasts."""
    query: str | None = Field(default=None, description="Natural language question, e.g. 'Forecast revenue for next 3 months'.")
    target_metric: str = Field(default="revenue", description="Target metric: revenue, sales, units, orders, product_demand.")
    forecast_horizon: int = Field(default=3, ge=1, le=12, description="Number of future periods to forecast (1 to 12).")
    frequency: str = Field(default="monthly", description="Frequency: daily, weekly, or monthly.")
    entity_type: str | None = Field(default=None, description="Optional entity scope: product, category, customer_segment.")
    entity_id: str | None = Field(default=None, description="Optional identifier for entity scope, e.g. SKU.")
    model_policy: ModelPolicy = Field(default=ModelPolicy.VALIDATED_BEST, description="Policy: validated_best, baseline_only, specific_model.")
    specific_model: str | None = Field(default=None, description="Name of specific model if policy is specific_model.")
    confidence_level: float = Field(default=0.95, ge=0.50, le=0.99, description="Coverage probability for prediction intervals.")
    explanation_level: str = Field(default="manager", description="manager, analyst, or technical.")
    reference_date: date | None = Field(default=None, description="Anchor reference date for relative inquiries.")


class ForecastAnalyzeRequest(BaseModel):
    """Natural language API request payload for Section 29 analyze endpoint."""
    query: str = Field(..., min_length=1, description="Natural language forecast question, e.g. 'Forecast revenue for next 3 months'.")
    explanation_level: str = Field(default="manager", description="Explanation detail level: simple, manager, analyst, or technical.")
    reference_date: date | None = Field(default=None, description="Reference anchor date for relative inquiries.")


class ForecastResponse(BaseModel):
    """API response conforming to Section 30 schema."""
    forecast_id: str
    status: str
    target_metric: str
    frequency: str
    training_period: dict[str, str | None]
    forecast_period: dict[str, str | None]
    model: ModelMetadata
    predictions: list[ForecastPredictionPoint]
    evaluation: EvaluationMetrics
    data_quality: ForecastDataQuality
    evidence: ForecastEvidence
    assumptions: list[str]
    limitations: list[str]
    explanation: str
    created_at: str


def forecast_result_to_response(result: ForecastResult) -> ForecastResponse:
    """Convert internal ForecastResult to API ForecastResponse."""
    return ForecastResponse(
        forecast_id=result.forecast_id,
        status=result.status.value if hasattr(result.status, "value") else str(result.status),
        target_metric=result.target_metric.value if hasattr(result.target_metric, "value") else str(result.target_metric),
        frequency=result.frequency.value if hasattr(result.frequency, "value") else str(result.frequency),
        training_period=result.training_period,
        forecast_period=result.forecast_period,
        model=result.model,
        predictions=result.predictions,
        evaluation=result.evaluation,
        data_quality=result.data_quality,
        evidence=result.evidence,
        assumptions=result.assumptions,
        limitations=result.limitations,
        explanation=result.explanation,
        created_at=result.created_at,
    )

