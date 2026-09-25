"""Temporal backtesting engine enforcing strict historical ordering without data leakage."""

from dataclasses import dataclass
from typing import Any

import numpy as np

from app.predictive.evaluation.metrics import evaluate_forecast
from app.predictive.models.base import BaseForecaster
from app.predictive.schemas import EvaluationMetrics


@dataclass
class BacktestResult:
    """Detailed summary of backtesting execution across temporal cutoffs."""
    model_name: str
    metrics: EvaluationMetrics
    splits_count: int
    validation_points: int
    predictions: list[float]
    actuals: list[float]


@dataclass
class BacktestSplitResult:
    """Result of a single expanding-window backtesting fold."""
    split_index: int
    cutoff_index: int
    train_size: int
    actuals: list[float]
    prediction: Any
    metrics: EvaluationMetrics


class ExpandingWindowBacktester:
    """
    Simulates real-world iterative deployment by training on historical periods up to cutoff t,
    generating forecasts for t+1..t+h, and assessing prediction error against observed actuals.
    Zero future leakage: training arrays strictly precede validation intervals.
    """

    def __init__(
        self,
        min_train_periods: int = 4,
        horizon: int = 1,
        max_splits: int = 5,
    ) -> None:
        self.min_train_periods = min_train_periods
        self.horizon = horizon
        self.max_splits = max_splits

    def backtest(self, model: BaseForecaster, y: Any) -> list[BacktestSplitResult]:
        """Execute expanding window backtesting over historical series."""
        import copy

        from app.predictive.schemas import ForecastPredictionPoint

        arr = y.values if hasattr(y, "values") else np.asarray(y, dtype=np.float64)
        n = len(arr)
        min_train = self.min_train_periods
        if n <= min_train:
            min_train = max(2, n - 1)

        split_results: list[BacktestSplitResult] = []
        cutoff = min_train
        split_idx = 0

        while cutoff < n and split_idx < self.max_splits:
            train_slice = arr[:cutoff]
            test_h = min(self.horizon, n - cutoff)
            actuals = arr[cutoff : cutoff + test_h]

            m = copy.deepcopy(model)
            m.fit(train_slice)
            preds = m.predict(test_h)
            lower, upper = m.get_prediction_intervals(test_h)

            point_obj = ForecastPredictionPoint(
                period=f"step_{split_idx+1}",
                point_forecast=float(preds[0]),
                lower_bound=float(lower[0]),
                upper_bound=float(upper[0]),
            )
            step_metrics = evaluate_forecast(actuals, preds)
            split_results.append(
                BacktestSplitResult(
                    split_index=split_idx,
                    cutoff_index=cutoff,
                    train_size=len(train_slice),
                    actuals=actuals.tolist(),
                    prediction=point_obj,
                    metrics=step_metrics,
                )
            )
            split_idx += 1
            cutoff += 1

        return split_results

    @classmethod
    def evaluate(
        cls,
        forecaster_factory: Any,
        y: np.ndarray,
        horizon: int = 1,
        min_train_size: int | None = None,
        max_splits: int = 5,
    ) -> BacktestResult:
        """
        Execute expanding-window backtesting.

        Args:
            forecaster_factory: Callable returning a fresh, unfitted BaseForecaster.
            y: Chronologically sorted 1D numpy array of historical observations.
            horizon: Out-of-sample steps to forecast at each cutoff.
            min_train_size: Minimum number of historical observations required before first cutoff.
            max_splits: Maximum number of temporal evaluation cutoffs.

        Returns:
            BacktestResult containing aggregate out-of-sample error metrics.
        """
        arr = np.asarray(y, dtype=np.float64)
        n = len(arr)

        if n < 3:
            # Series too short for multi-step backtesting; evaluate on last point or in-sample diff
            model = forecaster_factory()
            model.fit(arr[:-1] if n > 1 else arr)
            preds = model.predict(1)
            actuals = arr[-1:] if n > 1 else arr
            metrics = evaluate_forecast(actuals, preds)
            return BacktestResult(
                model_name=model.name,
                metrics=metrics,
                splits_count=1,
                validation_points=len(actuals),
                predictions=preds.tolist(),
                actuals=actuals.tolist(),
            )

        # Set default minimum training size
        if min_train_size is None:
            min_train_size = max(2, n // 2)

        # Number of possible cutoffs
        total_test_points = n - min_train_size
        if total_test_points <= 0:
            min_train_size = max(2, n - 1)
            total_test_points = n - min_train_size

        splits_count = min(max_splits, total_test_points)
        step_stride = max(1, total_test_points // splits_count)

        all_actuals: list[float] = []
        all_preds: list[float] = []
        actual_splits = 0

        # Walk through time sequentially: cutoff advances forward only
        cutoff = min_train_size
        while cutoff < n:
            train_data = arr[:cutoff]
            test_h = min(horizon, n - cutoff)
            actual_window = arr[cutoff : cutoff + test_h]

            # Fit brand new instance strictly on training slice
            model = forecaster_factory()
            model.fit(train_data)

            # Predict test horizon
            step_preds = model.predict(test_h)

            all_actuals.extend(actual_window.tolist())
            all_preds.extend(step_preds.tolist())
            actual_splits += 1

            cutoff += step_stride
            if actual_splits >= splits_count:
                break

        metrics = evaluate_forecast(all_actuals, all_preds)
        sample_model = forecaster_factory()

        return BacktestResult(
            model_name=sample_model.name,
            metrics=metrics,
            splits_count=actual_splits,
            validation_points=len(all_actuals),
            predictions=all_preds,
            actuals=all_actuals,
        )
