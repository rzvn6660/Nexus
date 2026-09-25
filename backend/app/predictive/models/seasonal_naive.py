"""Seasonal Naive baseline forecaster mapping future steps to corresponding historical seasons."""

import numpy as np

from app.predictive.models.base import BaseForecaster


class SeasonalNaiveForecaster(BaseForecaster):
    """
    Seasonal naive forecaster:
    y_hat_{T+h} = y_{T+h - m * k}
    where m is the seasonal period length (e.g. 12 for monthly, 7 for daily).
    """

    def __init__(self, season_length: int = 12) -> None:
        super().__init__(name="seasonal_naive", version="1.0", is_baseline=True)
        self.season_length = season_length

    def fit(self, y: np.ndarray) -> "SeasonalNaiveForecaster":
        arr = np.asarray(y, dtype=np.float64)
        if len(arr) == 0:
            raise ValueError("SeasonalNaiveForecaster requires at least 1 observation.")
        self._y_train = arr

        # Adjust season length if training series is shorter than configured season
        m = self.season_length if len(arr) >= self.season_length else max(1, len(arr))
        self._effective_m = m

        if len(arr) > m:
            self._residuals = arr[m:] - arr[:-m]
        else:
            self._residuals = arr[1:] - arr[:-1] if len(arr) > 1 else np.array([0.0])

        self._params = {
            "season_length": self.season_length,
            "effective_season_length": self._effective_m,
        }
        self._fitted = True
        return self

    def predict(self, horizon: int, confidence_level: float | None = None):
        if not self._fitted:
            raise ValueError("Model must be fitted prior to prediction.")
        m = self._effective_m
        y = self._y_train
        preds = []
        for h in range(1, horizon + 1):
            # Step back by effective period
            idx = len(y) - m + ((h - 1) % m)
            preds.append(float(y[idx]))
        raw = np.asarray(preds, dtype=np.float64)
        if confidence_level is not None:
            return self._points_from_raw(raw, horizon, confidence_level)
        return raw
