"""Exponential Smoothing forecaster supporting level and trend tracking."""

import numpy as np
from scipy.optimize import minimize

from app.predictive.models.base import BaseForecaster


class ExponentialSmoothingForecaster(BaseForecaster):
    """
    Holt's Linear Exponential Smoothing model:
    L_t = alpha * y_t + (1 - alpha) * (L_{t-1} + T_{t-1})
    T_t = beta * (L_t - L_{t-1}) + (1 - beta) * T_{t-1}
    y_hat_{T+h} = L_T + h * T_T
    """

    def __init__(self, alpha: float | None = None, beta: float | None = None) -> None:
        super().__init__(name="exponential_smoothing", version="1.0", is_baseline=True)
        self.alpha_init = alpha
        self.beta_init = beta

    def fit(self, y: np.ndarray) -> "ExponentialSmoothingForecaster":
        arr = np.asarray(y, dtype=np.float64)
        if len(arr) == 0:
            raise ValueError("ExponentialSmoothingForecaster requires at least 1 observation.")
        self._y_train = arr

        n = len(arr)
        if n < 3:
            # Fall back to single-observation / simple smoothing
            self._alpha = 0.3
            self._beta = 0.0
            self._final_level = float(arr[-1])
            self._final_trend = 0.0
            self._residuals = arr[1:] - arr[:-1] if n > 1 else np.array([0.0])
            self._params = {"alpha": self._alpha, "beta": self._beta, "final_level": round(self._final_level, 2), "final_trend": 0.0}
            self._fitted = True
            return self

        # Objective function for parameter optimization
        def _sse(params: tuple[float, float]) -> float:
            a, b = params
            lvl = arr[0]
            trd = arr[1] - arr[0]
            sse = 0.0
            for t in range(n):
                pred = lvl + trd
                err = arr[t] - pred
                sse += err * err
                new_lvl = a * arr[t] + (1.0 - a) * (lvl + trd)
                new_trd = b * (new_lvl - lvl) + (1.0 - b) * trd
                lvl, trd = new_lvl, new_trd
            return float(sse)

        if self.alpha_init is not None and self.beta_init is not None:
            best_a, best_b = self.alpha_init, self.beta_init
        else:
            try:
                res = minimize(
                    _sse,
                    x0=[0.3, 0.1],
                    bounds=[(0.01, 0.99), (0.0, 0.5)],
                    method="L-BFGS-B",
                )
                best_a, best_b = float(res.x[0]), float(res.x[1])
            except Exception:  # noqa: BLE001
                best_a, best_b = 0.3, 0.1

        # Re-run filter with best parameters to store final level, trend, and residuals
        lvl = arr[0]
        trd = arr[1] - arr[0] if n > 1 else 0.0
        resids = []
        for t in range(n):
            pred = lvl + trd
            resids.append(arr[t] - pred)
            new_lvl = best_a * arr[t] + (1.0 - best_a) * (lvl + trd)
            new_trd = best_b * (new_lvl - lvl) + (1.0 - best_b) * trd
            lvl, trd = new_lvl, new_trd

        self._alpha = round(best_a, 4)
        self._beta = round(best_b, 4)
        self._final_level = float(lvl)
        self._final_trend = float(trd)
        self._residuals = np.asarray(resids, dtype=np.float64)

        self._params = {
            "alpha": self._alpha,
            "beta": self._beta,
            "final_level": round(self._final_level, 2),
            "final_trend": round(self._final_trend, 2),
        }
        self._fitted = True
        return self

    @property
    def alpha(self) -> float | None:
        return self._alpha

    @property
    def beta(self) -> float | None:
        return self._beta

    def predict(self, horizon: int, confidence_level: float | None = None):
        if not self._fitted:
            raise ValueError("Model must be fitted prior to prediction.")
        steps = np.arange(1, horizon + 1)
        preds = self._final_level + steps * self._final_trend
        raw = np.maximum(0.0, np.round(preds, 2))
        if confidence_level is not None:
            return self._points_from_raw(raw, horizon, confidence_level)
        return raw
