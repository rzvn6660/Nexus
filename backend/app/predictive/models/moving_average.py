"""Moving Average baseline forecaster."""

import numpy as np

from app.predictive.models.base import BaseForecaster


class MovingAverageForecaster(BaseForecaster):
    """
    Moving Average baseline forecaster:
    y_hat_{T+h} = (1/k) * sum_{i=0}^{k-1} y_{T-i}
    """

    def __init__(self, window_size: int = 3, window: int | None = None) -> None:
        effective_w = window if window is not None else window_size
        super().__init__(name="moving_average", version="1.0", is_baseline=True)
        self.window_size = effective_w

    def fit(self, y: np.ndarray) -> "MovingAverageForecaster":
        arr = np.asarray(y, dtype=np.float64)
        if len(arr) == 0:
            raise ValueError("MovingAverageForecaster requires at least 1 observation.")
        self._y_train = arr

        k = min(self.window_size, len(arr))
        self._effective_k = k
        self._mean_val = float(np.mean(arr[-k:]))

        # Calculate in-sample residuals over rolling window
        resids = []
        for i in range(k, len(arr)):
            past_mean = float(np.mean(arr[i - k : i]))
            resids.append(arr[i] - past_mean)
        self._residuals = np.asarray(resids, dtype=np.float64) if resids else np.array([0.0])

        self._params = {
            "window_size": self.window_size,
            "effective_window": self._effective_k,
            "window_mean": round(self._mean_val, 2),
        }
        self._fitted = True
        return self

    def predict(self, horizon: int, confidence_level: float | None = None):
        if not self._fitted:
            raise ValueError("Model must be fitted prior to prediction.")
        raw = np.full(horizon, self._mean_val, dtype=np.float64)
        if confidence_level is not None:
            return self._points_from_raw(raw, horizon, confidence_level)
        return raw
