"""Naive benchmark forecaster predicting the most recent historical observation."""

import numpy as np

from app.predictive.models.base import BaseForecaster


class NaiveForecaster(BaseForecaster):
    """
    Random walk / naive benchmark model:
    y_hat_{t+h} = y_t
    """

    def __init__(self) -> None:
        super().__init__(name="naive", version="1.0", is_baseline=True)

    def fit(self, y: np.ndarray) -> "NaiveForecaster":
        arr = np.asarray(y, dtype=np.float64)
        if len(arr) == 0:
            raise ValueError("NaiveForecaster requires at least 1 observation.")
        self._y_train = arr
        self._last_val = float(arr[-1])
        if len(arr) > 1:
            self._residuals = arr[1:] - arr[:-1]
        else:
            self._residuals = np.array([0.0])
        self._params = {"last_value": round(self._last_val, 2)}
        self._fitted = True
        return self

    def predict(self, horizon: int, confidence_level: float | None = None):
        if not self._fitted:
            raise ValueError("Model must be fitted prior to prediction.")
        raw = np.full(horizon, self._last_val, dtype=np.float64)
        if confidence_level is not None:
            return self._points_from_raw(raw, horizon, confidence_level)
        return raw
