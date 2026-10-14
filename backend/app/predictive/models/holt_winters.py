"""Triple Exponential Smoothing (Holt-Winters) supporting additive and multiplicative seasonality."""

import numpy as np
from scipy.optimize import minimize

from app.predictive.models.base import BaseForecaster


class HoltWintersForecaster(BaseForecaster):
    """
    Holt-Winters Triple Exponential Smoothing forecaster.
    Models level (alpha), trend (beta), and seasonal cyclical variations (gamma)
    across a defined seasonal cycle length m (e.g. 12 for monthly, 7 for daily).

    Supports:
    - Additive Seasonality: y_hat_{T+h} = L_T + h * T_T + S_{T + 1 + ((h - 1) % m) - m}
    - Multiplicative Seasonality: y_hat_{T+h} = (L_T + h * T_T) * S_{T + 1 + ((h - 1) % m) - m}
    """

    def __init__(
        self,
        season_length: int = 12,
        seasonal_type: str = "additive",
        alpha: float | None = None,
        beta: float | None = None,
        gamma: float | None = None,
    ) -> None:
        super().__init__(name="holt_winters", version="1.0", is_baseline=False)
        self.season_length = max(2, int(season_length))
        self.seasonal_type = seasonal_type.lower().strip()
        self.alpha_init = alpha
        self.beta_init = beta
        self.gamma_init = gamma

        self._alpha = 0.2
        self._beta = 0.1
        self._gamma = 0.1
        self._final_level = 0.0
        self._final_trend = 0.0
        self._seasonal_indices: np.ndarray = np.array([])

    def fit(self, y: np.ndarray) -> "HoltWintersForecaster":
        arr = np.asarray(y, dtype=np.float64)
        n = len(arr)
        m = self.season_length

        if n < m:
            raise ValueError(
                f"HoltWinters requires at least one full seasonal cycle ({m} observations; received {n})."
            )
        self._y_train = arr

        # Auto-adjust multiplicative seasonality to additive if non-positive values exist
        is_mult = self.seasonal_type == "multiplicative" and np.all(arr > 1e-4)
        self._is_mult = is_mult

        # Initialize Level, Trend, and Seasonal components
        if n >= 2 * m:
            # Multi-cycle average initialization
            cycles = n // m
            cycle_means = [np.mean(arr[c * m : (c + 1) * m]) for c in range(cycles)]
            init_level = float(cycle_means[0])
            init_trend = float((cycle_means[-1] - cycle_means[0]) / max(1, (cycles - 1) * m))

            if is_mult:
                init_season = np.zeros(m)
                for c in range(cycles):
                    init_season += arr[c * m : (c + 1) * m] / max(1e-4, cycle_means[c])
                init_season /= cycles
                init_season /= np.mean(init_season)  # normalize so mean = 1
            else:
                init_season = np.zeros(m)
                for c in range(cycles):
                    init_season += arr[c * m : (c + 1) * m] - cycle_means[c]
                init_season /= cycles
                init_season -= np.mean(init_season)  # normalize so sum = 0
        else:
            # Single-cycle initialization
            init_level = float(np.mean(arr[:m]))
            init_trend = float((arr[m - 1] - arr[0]) / max(1, m - 1)) if m > 1 else 0.0
            if is_mult:
                init_season = arr[:m] / max(1e-4, init_level)
                init_season /= np.mean(init_season)
            else:
                init_season = arr[:m] - init_level
                init_season -= np.mean(init_season)

        def _forward_pass(a: float, b: float, g: float) -> tuple[float, np.ndarray, float, float, np.ndarray]:
            lvl = init_level
            trd = init_trend
            s_arr = init_season.copy()
            residuals = np.zeros(n)
            sse = 0.0

            for t in range(n):
                s_idx = t % m
                s_val = s_arr[s_idx]

                if is_mult:
                    pred = (lvl + trd) * s_val
                    pred = max(0.0, pred)
                    err = arr[t] - pred
                    new_lvl = a * (arr[t] / max(1e-4, s_val)) + (1.0 - a) * (lvl + trd)
                    new_trd = b * (new_lvl - lvl) + (1.0 - b) * trd
                    new_s = g * (arr[t] / max(1e-4, new_lvl)) + (1.0 - g) * s_val
                else:
                    pred = lvl + trd + s_val
                    err = arr[t] - pred
                    new_lvl = a * (arr[t] - s_val) + (1.0 - a) * (lvl + trd)
                    new_trd = b * (new_lvl - lvl) + (1.0 - b) * trd
                    new_s = g * (arr[t] - new_lvl) + (1.0 - g) * s_val

                residuals[t] = err
                sse += err * err
                lvl, trd = new_lvl, new_trd
                s_arr[s_idx] = new_s

            return float(sse), residuals, lvl, trd, s_arr

        if (
            self.alpha_init is not None
            and self.beta_init is not None
            and self.gamma_init is not None
        ):
            best_a, best_b, best_g = self.alpha_init, self.beta_init, self.gamma_init
        else:
            def _obj(params: tuple[float, float, float]) -> float:
                a, b, g = params
                sse, _, _, _, _ = _forward_pass(a, b, g)
                return sse

            try:
                res = minimize(
                    _obj,
                    x0=[0.2, 0.1, 0.1],
                    bounds=[(0.01, 0.99), (0.001, 0.99), (0.001, 0.99)],
                    method="L-BFGS-B",
                )
                if res.success:
                    best_a, best_b, best_g = float(res.x[0]), float(res.x[1]), float(res.x[2])
                else:
                    best_a, best_b, best_g = 0.2, 0.1, 0.1
            except Exception:  # noqa: BLE001
                best_a, best_b, best_g = 0.2, 0.1, 0.1

        _, residuals, final_lvl, final_trd, final_season = _forward_pass(best_a, best_b, best_g)

        self._alpha = best_a
        self._beta = best_b
        self._gamma = best_g
        self._final_level = final_lvl
        self._final_trend = final_trd
        self._seasonal_indices = final_season
        self._residuals = residuals

        self._params = {
            "alpha": round(best_a, 4),
            "beta": round(best_b, 4),
            "gamma": round(best_g, 4),
            "season_length": m,
            "seasonal_type": "multiplicative" if is_mult else "additive",
            "final_level": round(final_lvl, 2),
            "final_trend": round(final_trd, 2),
            "cycle_count": round(n / m, 2),
        }
        self._fitted = True
        return self

    def predict(self, horizon: int) -> np.ndarray:
        if not self._fitted:
            raise ValueError("Model must be fitted prior to prediction.")
        if horizon < 1:
            return np.array([])

        m = self.season_length
        lvl = self._final_level
        trd = self._final_trend
        s_arr = self._seasonal_indices
        n = len(self._y_train)

        preds = np.zeros(horizon, dtype=np.float64)
        for h in range(1, horizon + 1):
            s_idx = (n + h - 1) % m
            s_val = s_arr[s_idx]

            if self._is_mult:
                val = (lvl + h * trd) * s_val
            else:
                val = lvl + h * trd + s_val

            preds[h - 1] = max(0.0, val)

        return np.round(preds, 2)
