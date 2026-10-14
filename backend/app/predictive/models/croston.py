"""Croston's intermittent demand forecasting method with Syntetos-Boylan Approximation (SBA)."""

import numpy as np

from app.predictive.models.base import BaseForecaster


class CrostonForecaster(BaseForecaster):
    """
    Croston's Method with Syntetos-Boylan Approximation (SBA) for intermittent and lumpy demand.
    Specifically designed for retail and wholesale distribution where historical transaction series
    exhibit high zero-demand frequency (e.g., slow-moving SKUs or sporadic B2B orders).

    Decomposes the time series into:
    1. Demand sizes (z_t): Magnitude of non-zero transactions.
    2. Inter-arrival intervals (p_t): Number of periods elapsed between consecutive non-zero transactions.

    Applies the Syntetos-Boylan bias-correction factor:
        y_hat = (1 - alpha / 2) * (z / p)
    """

    def __init__(self, alpha: float = 0.1, variant: str = "sba") -> None:
        super().__init__(name="croston", version="1.0", is_baseline=False)
        self.alpha = float(alpha)
        self.variant = variant.lower().strip()  # "sba" or "standard"
        self._fitted_rate = 0.0
        self._last_z = 0.0
        self._last_p = 1.0

    def fit(self, y: np.ndarray) -> "CrostonForecaster":
        arr = np.asarray(y, dtype=np.float64)
        if len(arr) == 0:
            raise ValueError("CrostonForecaster requires at least 1 observation.")
        if np.any(arr < -1e-6):
            raise ValueError("CrostonForecaster requires non-negative demand observations.")
        self._y_train = arr

        non_zero_indices = np.where(arr > 1e-6)[0]
        if len(non_zero_indices) < 2:
            # Degrade gracefully to simple mean of available observations if only 1 positive event
            if len(non_zero_indices) == 1:
                val = float(arr[non_zero_indices[0]])
                rate = val / float(len(arr))
                self._fitted_rate = rate
                self._last_z = val
                self._last_p = float(len(arr))
                self._residuals = arr - rate
                self._params = {
                    "alpha": self.alpha,
                    "variant": self.variant,
                    "demand_rate": round(rate, 4),
                    "non_zero_count": 1,
                    "zero_ratio": round(float(np.mean(arr == 0.0)), 3),
                }
                self._fitted = True
                return self
            raise ValueError("CrostonForecaster requires at least 1 non-zero demand observation.")

        # Extract non-zero demand magnitudes and intervals
        z_vals = arr[non_zero_indices]
        intervals = np.diff(np.insert(non_zero_indices, 0, -1))
        # First interval: distance from beginning of series
        intervals[0] = non_zero_indices[0] + 1

        z = float(z_vals[0])
        p = float(intervals[0])
        a = self.alpha

        for i in range(1, len(z_vals)):
            z = a * z_vals[i] + (1.0 - a) * z
            p = a * intervals[i] + (1.0 - a) * p

        self._last_z = z
        self._last_p = max(1.0, p)

        if self.variant == "sba":
            # Syntetos-Boylan Approximation bias-correction
            factor = 1.0 - (a / 2.0)
            self._fitted_rate = float(factor * (z / self._last_p))
        else:
            self._fitted_rate = float(z / self._last_p)

        # Residuals against the fitted demand rate
        self._residuals = arr - self._fitted_rate
        self._params = {
            "alpha": self.alpha,
            "variant": self.variant,
            "smoothed_demand_size": round(z, 2),
            "smoothed_interval": round(p, 2),
            "demand_rate": round(self._fitted_rate, 4),
            "non_zero_count": len(non_zero_indices),
            "zero_ratio": round(float(np.mean(arr == 0.0)), 3),
        }
        self._fitted = True
        return self

    def predict(self, horizon: int) -> np.ndarray:
        if not self._fitted:
            raise ValueError("Model must be fitted prior to prediction.")
        if horizon < 1:
            return np.array([])
        # Intermittent demand forecasts a flat expected demand rate across future periods
        point = max(0.0, self._fitted_rate)
        return np.full(horizon, point, dtype=np.float64)

    def get_prediction_intervals(
        self,
        horizon: int,
        confidence_level: float = 0.95,
    ) -> tuple[np.ndarray, np.ndarray]:
        """
        Derive prediction intervals for intermittent demand.
        Enforces physical non-negativity (lower_bound >= 0.0) and accounts for
        compound Poisson-normal variance across sporadic intervals.
        """
        point_preds = self.predict(horizon)
        if len(self._y_train) < 2:
            return np.zeros(horizon), point_preds

        # Variance of non-zero demands and intervals
        non_zero = self._y_train[self._y_train > 1e-6]
        if len(non_zero) > 1:
            var_z = float(np.var(non_zero, ddof=1))
        else:
            var_z = float(point_preds[0] ** 2)

        p = max(1.0, self._last_p)
        # Compound intermittent demand variance per period:
        # Var(Y) = (1/p) * Var(Z) + (1/p) * (1 - 1/p) * E(Z)^2
        var_per_period = (1.0 / p) * var_z + (1.0 / p) * (1.0 - 1.0 / p) * (self._last_z ** 2)
        std_err = float(np.sqrt(max(1e-6, var_per_period)))

        from scipy import stats
        alpha = 1.0 - confidence_level
        z_crit = float(stats.norm.ppf(1.0 - alpha / 2.0))

        # Prediction interval expands with horizon steps
        h_factors = np.sqrt(np.arange(1, horizon + 1))
        margin = z_crit * std_err * h_factors

        lower = np.maximum(0.0, point_preds - margin)
        upper = point_preds + margin

        return np.round(lower, 2), np.round(upper, 2)
