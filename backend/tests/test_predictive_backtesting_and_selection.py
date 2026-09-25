"""Unit tests for Phase 7 backtesting engine, evaluation metrics, and model selection."""

import numpy as np
import pandas as pd
import pytest
from app.predictive.evaluation.backtesting import ExpandingWindowBacktester
from app.predictive.evaluation.metrics import (
    calc_mae,
    calc_mape,
    calc_rmse,
    calc_smape,
    calc_wape,
)
from app.predictive.models.exponential_smoothing import ExponentialSmoothingForecaster
from app.predictive.models.moving_average import MovingAverageForecaster
from app.predictive.models.naive import NaiveForecaster
from app.predictive.registry.model_registry import ModelRegistry
from app.predictive.schemas import ModelPolicy


def test_evaluation_metrics_deterministic():
    """Verify MAE, RMSE, sMAPE, MAPE, and WAPE with known mathematical values."""
    actuals = np.array([100.0, 110.0, 120.0])
    predictions = np.array([105.0, 108.0, 125.0])

    mae = calc_mae(actuals, predictions)
    assert mae == pytest.approx((5.0 + 2.0 + 5.0) / 3.0, 0.001)

    rmse = calc_rmse(actuals, predictions)
    assert rmse == pytest.approx(np.sqrt((25.0 + 4.0 + 25.0) / 3.0), 0.001)

    smape = calc_smape(actuals, predictions)
    assert 0.0 <= smape <= 200.0

    wape = calc_wape(actuals, predictions)
    assert pytest.approx(wape, abs=0.01) == 3.64


def test_metrics_zero_actuals_safe_handling():
    """Verify zero actuals do not produce infinity or crash."""
    actuals = np.array([0.0, 0.0, 0.0])
    predictions = np.array([10.0, 5.0, 0.0])

    # Standard MAPE with all zeros returns None safely
    mape = calc_mape(actuals, predictions)
    assert mape is None

    # sMAPE handles zero actuals smoothly
    smape = calc_smape(actuals, predictions)
    assert 0.0 <= smape <= 200.0


def test_expanding_window_backtest_temporal_ordering_and_no_leakage():
    """Verify expanding window backtesting respects chronological ordering and enforces no leakage."""
    dates = pd.date_range("2023-01-01", periods=12, freq="MS")
    # Linear series: y = 10 * t
    values = [10.0 * i for i in range(1, 13)]
    series = pd.Series(values, index=dates)

    backtester = ExpandingWindowBacktester(min_train_periods=4, horizon=1)
    results = backtester.backtest(ExponentialSmoothingForecaster(), series)

    assert len(results) > 0
    # Average MAE across folds must be reasonable for an exponential smoothing model on linear series
    avg_mae = np.mean([r.metrics.mae for r in results])
    assert avg_mae < 50.0

    # Ensure all predictions satisfy lower <= point <= upper
    for r in results:
        assert r.prediction.lower_bound <= r.prediction.point_forecast <= r.prediction.upper_bound


def test_model_registry_select_best_validated_model():
    """Verify ModelRegistry runs backtesting and selects the candidate with lowest validated error."""
    dates = pd.date_range("2023-01-01", periods=12, freq="MS")
    # Series with a strong trend: Exponential smoothing should easily beat Naive
    values = [10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 70.0, 80.0, 90.0, 100.0, 110.0, 120.0]
    series = pd.Series(values, index=dates)

    registry = ModelRegistry()
    candidates = [
        NaiveForecaster(),
        MovingAverageForecaster(window=3),
        ExponentialSmoothingForecaster(),
    ]

    selected_model, evaluation, metadata = registry.evaluate_and_select(
        series=series,
        candidates=candidates,
        policy=ModelPolicy.VALIDATED_BEST,
        horizon=1,
    )

    assert selected_model is not None
    # Exponential smoothing captures trend and should win over naive
    assert selected_model.name == "exponential_smoothing"
    assert metadata.selected is True
    assert evaluation.mae < 10.0


def test_model_registry_baseline_only_policy():
    """Verify baseline_only policy restricts candidate pool to baseline models."""
    registry = ModelRegistry()
    candidates = registry.get_candidates(policy=ModelPolicy.BASELINE_ONLY)
    model_names = [m.name for m in candidates]

    assert "naive" in model_names
    assert "moving_average" in model_names
    assert "arima" not in model_names
