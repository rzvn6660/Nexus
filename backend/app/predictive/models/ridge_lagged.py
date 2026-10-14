"""Autoregressive Ridge Regression forecaster with lagged features and cyclical calendar encoding."""

import numpy as np

from app.predictive.models.base import BaseForecaster


class RidgeLaggedForecaster(BaseForecaster):
    """
    Penalized Autoregressive Ridge Regression forecaster.
    Constructs leakage-safe chronological lag matrices: [y_{t-1}, y_{t-2}, ..., y_{t-p}],
    normalized trend, and cyclical harmonics without future lookahead.

    Solves for closed-form L2-regularized coefficients:
        beta = (X^T X + lambda * I)^(-1) X^T y
    Guarantees deterministic, reproducible, and non-overfitted parameter estimates.
    """

    def __init__(
        self,
        max_lags: int = 3,
        l2_penalty: float = 1.0,
        season_length: int | None = None,
    ) -> None:
        super().__init__(name="ridge_lagged", version="1.0", is_baseline=False)
        self.max_lags = max(1, int(max_lags))
        self.l2_penalty = max(1e-4, float(l2_penalty))
        self.season_length = season_length

        self._lags = self.max_lags
        self._weights: np.ndarray = np.array([])
        self._intercept: float = 0.0

    def _build_feature_row(self, lag_vals: np.ndarray, t_idx: int, total_n: int) -> np.ndarray:
        """Construct a single row of features for time t_idx given previous lag values."""
        feats = list(lag_vals)
        # Normalized linear trend
        feats.append(float(t_idx) / max(1.0, float(total_n)))

        # Cyclical harmonics if seasonal period is provided
        if self.season_length and self.season_length > 1:
            m = float(self.season_length)
            feats.append(float(np.sin(2.0 * np.pi * (t_idx % m) / m)))
            feats.append(float(np.cos(2.0 * np.pi * (t_idx % m) / m)))

        # Bias intercept
        feats.append(1.0)
        return np.asarray(feats, dtype=np.float64)

    def fit(self, y: np.ndarray) -> "RidgeLaggedForecaster":
        arr = np.asarray(y, dtype=np.float64)
        n = len(arr)

        # Adapt lag count to sample size: need at least lags + 3 points
        effective_lags = min(self.max_lags, max(1, n - 3))
        if n < effective_lags + 2:
            raise ValueError(
                f"RidgeLaggedForecaster requires at least {effective_lags + 2} observations (received {n})."
            )

        self._y_train = arr
        self._lags = effective_lags

        # Construct strictly chronological feature matrix X and targets Y
        # Target t corresponds to features from [t - lags, ..., t - 1]
        X_rows = []
        Y_vals = []

        for t in range(effective_lags, n):
            lag_slice = arr[t - effective_lags : t][::-1]  # [y_{t-1}, y_{t-2}, ...]
            row = self._build_feature_row(lag_slice, t, n)
            X_rows.append(row)
            Y_vals.append(arr[t])

        X = np.asarray(X_rows, dtype=np.float64)
        Y = np.asarray(Y_vals, dtype=np.float64)

        # Closed-form Ridge solution with L2 regularization penalty
        d = X.shape[1]
        reg_matrix = self.l2_penalty * np.eye(d)
        # Do not regularize the intercept term (last column)
        reg_matrix[-1, -1] = 1e-6

        XtX = X.T @ X
        XtY = X.T @ Y

        try:
            weights = np.linalg.solve(XtX + reg_matrix, XtY)
        except np.linalg.LinAlgError:
            weights = np.linalg.pinv(XtX + reg_matrix) @ XtY

        self._weights = weights
        self._intercept = float(weights[-1])

        # Fitted residuals on training slice
        in_sample_preds = X @ weights
        self._residuals = Y - in_sample_preds

        self._params = {
            "lags": self._lags,
            "l2_penalty": self.l2_penalty,
            "season_length": self.season_length,
            "feature_dim": d,
            "weights": [round(float(w), 4) for w in weights],
            "in_sample_mae": round(float(np.mean(np.abs(self._residuals))), 2),
        }
        self._fitted = True
        return self

    def predict(self, horizon: int) -> np.ndarray:
        if not self._fitted:
            raise ValueError("Model must be fitted prior to prediction.")
        if horizon < 1:
            return np.array([])

        preds = []
        history = list(self._y_train)
        n = len(history)

        for h in range(1, horizon + 1):
            t_curr = n + h - 1
            # Extract most recent effective_lags values from extended history
            recent_lags = np.asarray(history[-self._lags :][::-1], dtype=np.float64)
            feat_row = self._build_feature_row(recent_lags, t_curr, n)
            y_next = float(feat_row @ self._weights)
            y_next = max(0.0, y_next)  # non-negativity constraint
            preds.append(y_next)
            history.append(y_next)

        return np.round(np.asarray(preds, dtype=np.float64), 2)
