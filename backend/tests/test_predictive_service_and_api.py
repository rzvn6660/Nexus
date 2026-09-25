"""Integration tests for ForecastingService and Phase 7 API endpoints."""

from app.core.config import settings
from app.predictive.schemas import ForecastStatus
from app.predictive.services.forecasting_service import ForecastingService
from fastapi.testclient import TestClient


def test_forecasting_service_end_to_end_revenue(predictive_db_session):
    """Verify ForecastingService executes full pipeline against database sales."""
    service = ForecastingService(predictive_db_session)
    result = service.generate_forecast(
        target_metric="revenue",
        frequency="monthly",
        forecast_horizon=3,
        model_policy="validated_best",
    )

    assert result.status == ForecastStatus.COMPLETED
    assert len(result.predictions) == 3
    assert result.model.selected is True
    assert result.evidence.validation_metrics.mae >= 0.0

    # Validate interval invariant
    for p in result.predictions:
        assert p.lower_bound <= p.point_forecast <= p.upper_bound
        assert p.lower_bound >= 0.0

    # Explainer narrative must be present and contain required sections
    assert "### Forecast" in result.explanation
    assert "### Model" in result.explanation
    assert "### Uncertainty" in result.explanation


def test_forecasting_service_insufficient_data(db_session):
    """Verify ForecastingService returns unavailable status when database has no sales."""
    service = ForecastingService(db_session)
    result = service.generate_forecast(
        target_metric="revenue",
        frequency="monthly",
        forecast_horizon=3,
    )

    assert result.status == ForecastStatus.UNAVAILABLE
    assert len(result.predictions) == 0
    assert any("insufficient" in r.lower() for r in result.data_quality.blocking_reasons)


def test_forecast_api_natural_language_analyze(api_client: TestClient, predictive_db_session):
    """Verify POST /api/v1/forecast/analyze endpoint processes natural language request."""
    response = api_client.post(
        "/api/v1/forecast/analyze",
        json={
            "query": "Forecast revenue for the next 3 months",
            "explanation_level": "manager",
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "completed"
    assert data["target_metric"] == "revenue"
    assert len(data["predictions"]) == 3
    assert "model" in data
    assert "evaluation" in data
    assert "explanation" in data


def test_forecast_api_structured_endpoint(api_client: TestClient, predictive_db_session):
    """Verify POST /api/v1/forecast endpoint accepts structured request."""
    response = api_client.post(
        "/api/v1/forecast",
        json={
            "target_metric": "sales",
            "forecast_horizon": 2,
            "frequency": "monthly",
            "model_policy": "validated_best",
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "completed"
    assert len(data["predictions"]) == 2
    for p in data["predictions"]:
        assert p["lower_bound"] <= p["point_forecast"] <= p["upper_bound"]


def test_forecast_api_excessive_horizon_rejected(api_client: TestClient):
    """Verify requesting horizon beyond MAX_FORECAST_HORIZON returns 422 error."""
    response = api_client.post(
        "/api/v1/forecast",
        json={
            "target_metric": "revenue",
            "forecast_horizon": settings.MAX_FORECAST_HORIZON + 5,
            "frequency": "monthly",
        },
    )
    assert response.status_code == 422


def test_forecast_api_invalid_target_rejected(api_client: TestClient):
    """Verify requesting an unsupported target metric returns 422 error."""
    response = api_client.post(
        "/api/v1/forecast",
        json={
            "target_metric": "invalid_nonexistent_metric",
            "forecast_horizon": 3,
            "frequency": "monthly",
        },
    )
    assert response.status_code == 422
