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

    # Model provenance identity in API response
    assert data["model"]["name"] == data["evidence"]["model"]
    assert data["model"]["name"] == data["evidence"]["selected_model"]
    assert data["model"]["version"] == data["evidence"]["model_version"]
    assert data["evidence"]["validation_metrics"]["mae"] == data["evaluation"]["mae"]

    # Lineage provenance for order-level revenue in API response
    assert data["evidence"]["source_tables"] == ["sales"]
    assert data["evidence"]["source_columns"] == ["transaction_date", "total_amount", "status", "id"]
    assert "sale_items" not in data["evidence"]["source_tables"]
    assert "products" not in data["evidence"]["source_tables"]
    assert data["evidence"]["telemetry_source"] == "order_level_sales_telemetry"


def test_forecast_selected_model_provenance_identity(predictive_db_session):
    """
    Regression test asserting selected_model == provenance.model identity.
    Ensures that the actual model chosen during out-of-sample backtesting matches
    the model reported in audit evidence provenance, including model version and backtest metrics.
    """
    service = ForecastingService(predictive_db_session)
    result = service.generate_forecast(
        target_metric="revenue",
        frequency="monthly",
        forecast_horizon=3,
        model_policy="validated_best",
    )

    assert result.status == ForecastStatus.COMPLETED

    selected_model = result.model.name
    provenance_model = result.evidence.model

    # Strict identity: selected_model == provenance.model
    assert selected_model == provenance_model
    assert selected_model == result.evidence.selected_model
    assert result.evidence.selected_model == result.evidence.model
    assert result.model.version == result.evidence.model_version

    # Backtest evaluation metrics identity between result and provenance
    assert result.evidence.validation_metrics.mae == result.evaluation.mae
    assert result.evidence.validation_metrics.rmse == result.evaluation.rmse
    assert result.evidence.validation_metrics.smape == result.evaluation.smape

    # Candidate tournament evaluations must include the selected model with exact metrics
    assert selected_model in result.evidence.candidate_evaluations
    assert result.evidence.candidate_evaluations[selected_model]["mae"] == result.evaluation.mae


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


def test_forecast_order_level_provenance_lineage(predictive_db_session):
    """
    Verify order-level revenue forecast provenance accurately reflects that only
    the sales table was read, discloses order-level sales telemetry, and does not claim
    sale_items or products were used.
    """
    service = ForecastingService(predictive_db_session)
    result = service.generate_forecast(
        target_metric="revenue",
        frequency="monthly",
        forecast_horizon=3,
    )

    assert result.status == ForecastStatus.COMPLETED

    # 1. Source tables must strictly contain ONLY sales
    assert result.evidence.source_tables == ["sales"]
    assert "sale_items" not in result.evidence.source_tables
    assert "products" not in result.evidence.source_tables

    # 2. Source columns must strictly match order-level query columns
    assert result.evidence.source_columns == ["transaction_date", "total_amount", "status", "id"]
    assert "line_total" not in result.evidence.source_columns
    assert "quantity" not in result.evidence.source_columns

    # 3. Disclose order-level telemetry extraction mode
    assert result.evidence.telemetry_source == "order_level_sales_telemetry"

    # 4. Explicit disclosure in assumptions and limitations
    assert any("order-level sales telemetry" in a.lower() for a in result.evidence.assumptions)
    assert any("order-level sales telemetry fallback" in lim.lower() for lim in result.evidence.limitations)


def test_forecast_item_level_product_provenance_lineage(predictive_db_session):
    """
    Verify item-level product forecast genuinely queries and reports all three tables:
    sales, sale_items, and products.
    """
    service = ForecastingService(predictive_db_session)
    result = service.generate_forecast(
        target_metric="product_demand",
        frequency="monthly",
        forecast_horizon=3,
        entity_type="product",
        entity_id="SKU-PROD-A",
    )

    assert result.status == ForecastStatus.COMPLETED

    # Genuinely used all three tables
    assert set(result.evidence.source_tables) == {"sales", "sale_items", "products"}
    assert "quantity" in result.evidence.source_columns
    assert "line_total" in result.evidence.source_columns
    assert result.evidence.telemetry_source == "item_level_product_telemetry"
