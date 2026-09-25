"""Statistical ARIMA forecasting model utilizing statsmodels."""

import warnings
from typing import ClassVar

import numpy as np
from statsmodels.tsa.arima.model import ARIMA

from app.predictive.models.base import BaseForecaster


class ARIMAForecaster(BaseForecaster):
    """
    Classical Autoregressive Integrated Moving Average (ARIMA) forecaster.
    Evaluates parsimonious candidate orders (p,d,q) via AIC and fits the optimal parameterization.
    """

    CANDIDATE_ORDERS: ClassVar[list[tuple[int, int, int]]] = [
        (1, 0, 0),
        (0, 1, 1),
        (1, 1, 0),
        (1, 1, 1),
        (0, 1, 0),
    ]

    def __init__(self, order: tuple[int, int, int] | None = None) -> None:
        super().__init__(name="arima", version="1.0", is_baseline=False)
        self.preferred_order = order
        self._fitted_model = None
        self._best_order = order or (1, 1, 0)

    def fit(self, y: np.ndarray) -> "ARIMAForecaster":
        arr = np.asarray(y, dtype=np.float64)
        if len(arr) < 3:
            raise ValueError(f"ARIMA requires at least 3 historical points (received {len(arr)}).")
        self._y_train = arr

        best_aic = float("inf")
        best_fit = None
        best_order = (0, 1, 0)

        candidate_list = [self.preferred_order] if self.preferred_order else self.CANDIDATE_ORDERS

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            for order in candidate_list:
                try:
                    # Enforce stationarity and invertibility false for robustness on small series
                    model = ARIMA(arr, order=order, enforce_stationarity=False, enforce_invertibility=False)
                    fit_res = model.fit()
                    if fit_res.aic < best_aic:
                        best_aic = fit_res.aic
                        best_fit = fit_res
                        best_order = order
                except Exception:  # noqa: BLE001, S112
                    continue

        if best_fit is None:
            # Fallback to simple differenced AR(1)
            try:
                model = ARIMA(arr, order=(1, 0, 0), enforce_stationarity=False)
                best_fit = model.fit()
                best_order = (1, 0, 0)
                best_aic = best_fit.aic
            except Exception:  # noqa: BLE001
                # Ultimate fallback to naive
                self._residuals = arr[1:] - arr[:-1] if len(arr) > 1 else np.array([0.0])
                self._best_order = (0, 1, 0)
                self._params = {"order": (0, 1, 0), "aic": None, "fallback": True}
                self._fitted = True
                return self

        self._fitted_model = best_fit
        self._best_order = best_order
        self._residuals = np.asarray(best_fit.resid, dtype=np.float64)
        self._params = {
            "order": list(best_order),
            "aic": round(best_aic, 2) if np.isfinite(best_aic) else None,
            "fallback": False,
        }
        self._fitted = True
        return self

    @property
    def fitted_order(self) -> tuple[int, int, int]:
        return self._best_order

    def predict(self, horizon: int, confidence_level: float | None = None):
        if not self._fitted:
            raise ValueError("Model must be fitted prior to prediction.")
        if self._fitted_model is not None:
            try:
                forecast_res = self._fitted_model.get_forecast(steps=horizon)
                preds = np.asarray(forecast_res.predicted_mean, dtype=np.float64)
                raw = np.maximum(0.0, np.round(preds, 2))
                if confidence_level is not None:
                    return self._points_from_raw(raw, horizon, confidence_level)
                return raw
            except Exception:  # noqa: BLE001, S110
                pass
        # Fallback prediction to last value
        raw = np.full(horizon, float(self._y_train[-1]), dtype=np.float64)
        if confidence_level is not None:
            return self._points_from_raw(raw, horizon, confidence_level)
        return raw

    def get_prediction_intervals(
        self,
        horizon: int,
        confidence_level: float = 0.95,
    ) -> tuple[np.ndarray, np.ndarray]:
        if not self._fitted:
            raise ValueError("Model must be fitted prior to prediction.")
        point_preds = self.predict(horizon)
        if self._fitted_model is not None:
            try:
                alpha = 1.0 - confidence_level
                forecast_res = self._fitted_model.get_forecast(steps=horizon)
                ci = forecast_res.conf_int(alpha=alpha)
                lower = np.maximum(0.0, np.asarray(ci[:, 0], dtype=np.float64))
                upper = np.asarray(ci[:, 1], dtype=np.float64)
                # Guarantee lower <= point <= upper
                lower = np.minimum(lower, point_preds)
                upper = np.maximum(upper, point_preds)
                return np.round(lower, 2), np.round(upper, 2)
            except Exception:  # noqa: BLE001, S110
                pass
        return super().get_prediction_intervals(horizon, confidence_level=confidence_level)
