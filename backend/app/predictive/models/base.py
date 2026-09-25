"""Base protocol and abstract forecaster definition for predictive models."""

from abc import ABC, abstractmethod
from typing import Any

import numpy as np
from scipy import stats


class BaseForecaster(ABC):
    """
    Abstract base class for all deterministic baseline and statistical forecasting models.
    Guarantees consistent fit/predict APIs, parameter tracking, and prediction intervals.
    """

    def __init__(self, name: str, version: str = "1.0", is_baseline: bool = True) -> None:
        self.name = name
        self.version = version
        self.is_baseline = is_baseline
        self._fitted = False
        self._y_train: np.ndarray = np.array([])
        self._residuals: np.ndarray = np.array([])
        self._params: dict[str, Any] = {}

    @property
    def parameters(self) -> dict[str, Any]:
        """Expose fitted model parameters for audit and evidence provenance."""
        return self._params

    @abstractmethod
    def fit(self, y: np.ndarray) -> "BaseForecaster":
        """Fit model weights/parameters to historical observations."""

    @abstractmethod
    def predict(self, horizon: int) -> np.ndarray:
        """Generate out-of-sample point forecasts for the given horizon."""

    def get_prediction_intervals(
        self,
        horizon: int,
        confidence_level: float = 0.95,
    ) -> tuple[np.ndarray, np.ndarray]:
        """
        Derive statistically sound prediction intervals (lower_bound, upper_bound)
        at the specified confidence/coverage level.
        Guarantees lower_bound <= point_forecast <= upper_bound.
        """
        point_preds = self.predict(horizon)
        if len(self._residuals) > 1:
            std_err = float(np.std(self._residuals, ddof=1))
        elif len(self._y_train) > 1:
            std_err = float(np.std(self._y_train, ddof=1))
        else:
            std_err = float(np.abs(self._y_train[0])) * 0.10 if len(self._y_train) > 0 else 1.0

        # Normal critical value for two-tailed interval
        alpha = 1.0 - confidence_level
        z_crit = float(stats.norm.ppf(1.0 - alpha / 2.0))

        # Prediction interval expands with horizon steps: sqrt(h)
        h_factors = np.sqrt(np.arange(1, horizon + 1))
        margin = z_crit * std_err * h_factors

        lower = np.maximum(0.0, point_preds - margin)
        upper = point_preds + margin

        # Guarantee lower <= point <= upper
        lower = np.minimum(lower, point_preds)
        upper = np.maximum(upper, point_preds)

        return np.round(lower, 2), np.round(upper, 2)

    def _points_from_raw(self, raw: np.ndarray, horizon: int, confidence_level: float) -> list[Any]:
        """Convert raw numpy predictions and statistical bounds into structured prediction points."""
        lower, upper = self.get_prediction_intervals(horizon, confidence_level=confidence_level)
        from app.predictive.schemas import ForecastPredictionPoint
        points = []
        for h in range(1, horizon + 1):
            points.append(
                ForecastPredictionPoint(
                    period=f"t+{h}",
                    point_forecast=float(raw[h - 1]),
                    lower_bound=float(lower[h - 1]),
                    upper_bound=float(upper[h - 1]),
                    confidence_level=confidence_level,
                )
            )
        return points

