"""Unit tests for Phase 7 forecasting models and prediction intervals."""

import numpy as np
import pandas as pd
import pytest
from app.predictive.models.arima import ARIMAForecaster
from app.predictive.models.exponential_smoothing import ExponentialSmoothingForecaster
from app.predictive.models.moving_average import MovingAverageForecaster
from app.predictive.models.naive import NaiveForecaster
from app.predictive.models.seasonal_naive import SeasonalNaiveForecaster


@pytest.fixture
def sample_monthly_series() -> pd.Series:
    """12 months of synthetic retail demand with upward trend."""
    dates = pd.date_range("2023-01-01", periods=12, freq="MS")
    values = [100.0, 105.0, 110.0, 115.0, 120.0, 128.0, 132.0, 138.0, 145.0, 150.0, 158.0, 165.0]
    return pd.Series(values, index=dates)


def test_naive_forecaster(sample_monthly_series):
    """Verify NaiveForecaster predicts last observed value with widening intervals."""
    forecaster = NaiveForecaster()
    forecaster.fit(sample_monthly_series)

    preds = forecaster.predict(horizon=3, confidence_level=0.95)
    assert len(preds) == 3

    last_val = sample_monthly_series.iloc[-1]
    for p in preds:
        assert p.point_forecast == last_val
        assert p.lower_bound <= p.point_forecast <= p.upper_bound
        assert p.lower_bound >= 0.0

    # Horizon variance expansion: width of interval should increase with horizon
    width_1 = preds[0].upper_bound - preds[0].lower_bound
    width_3 = preds[2].upper_bound - preds[2].lower_bound
    assert width_3 > width_1


def test_seasonal_naive_forecaster(sample_monthly_series):
    """Verify SeasonalNaiveForecaster maps lag correctly or falls back to naive."""
    forecaster = SeasonalNaiveForecaster(season_length=12)
    forecaster.fit(sample_monthly_series)

    preds = forecaster.predict(horizon=3, confidence_level=0.95)
    assert len(preds) == 3
    for p in preds:
        assert p.lower_bound <= p.point_forecast <= p.upper_bound


def test_moving_average_forecaster(sample_monthly_series):
    """Verify MovingAverageForecaster computes rolling mean correctly."""
    forecaster = MovingAverageForecaster(window=3)
    forecaster.fit(sample_monthly_series)

    preds = forecaster.predict(horizon=2, confidence_level=0.95)
    assert len(preds) == 2

    # Expected point forecast is mean of last 3 elements (150, 158, 165) = 157.6667
    expected_mean = float(np.mean(sample_monthly_series.iloc[-3:].values))
    assert pytest.approx(preds[0].point_forecast, 0.01) == expected_mean
    for p in preds:
        assert p.lower_bound <= p.point_forecast <= p.upper_bound


def test_exponential_smoothing_forecaster(sample_monthly_series):
    """Verify ExponentialSmoothingForecaster captures trend and fits alpha/beta."""
    forecaster = ExponentialSmoothingForecaster()
    forecaster.fit(sample_monthly_series)

    preds = forecaster.predict(horizon=3, confidence_level=0.95)
    assert len(preds) == 3
    assert forecaster.alpha is not None
    assert forecaster.beta is not None

    # Trend should result in monotonically increasing forecasts for this series
    assert preds[1].point_forecast > preds[0].point_forecast
    assert preds[2].point_forecast > preds[1].point_forecast
    for p in preds:
        assert p.lower_bound <= p.point_forecast <= p.upper_bound


def test_arima_forecaster(sample_monthly_series):
    """Verify ARIMAForecaster fits candidate order and generates intervals."""
    forecaster = ARIMAForecaster()
    forecaster.fit(sample_monthly_series)

    preds = forecaster.predict(horizon=3, confidence_level=0.95)
    assert len(preds) == 3
    assert forecaster.fitted_order is not None

    for p in preds:
        assert p.lower_bound <= p.point_forecast <= p.upper_bound
        assert p.lower_bound >= 0.0


def test_forecaster_not_fitted_error():
    """Verify predicting before fitting raises ValueError."""
    forecaster = NaiveForecaster()
    with pytest.raises(ValueError, match="must be fitted"):
        forecaster.predict(horizon=2)
