"""Lightweight model registry and selection engine implementing the Principle of Parsimony."""

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, ClassVar

import numpy as np

from app.core.logging import get_logger
from app.predictive.evaluation.backtesting import ExpandingWindowBacktester
from app.predictive.models.arima import ARIMAForecaster
from app.predictive.models.base import BaseForecaster
from app.predictive.models.croston import CrostonForecaster
from app.predictive.models.exponential_smoothing import ExponentialSmoothingForecaster
from app.predictive.models.holt_winters import HoltWintersForecaster
from app.predictive.models.moving_average import MovingAverageForecaster
from app.predictive.models.naive import NaiveForecaster
from app.predictive.models.ridge_lagged import RidgeLaggedForecaster
from app.predictive.models.seasonal_naive import SeasonalNaiveForecaster
from app.predictive.schemas import EvaluationMetrics, ModelMetadata, ModelPolicy

logger = get_logger("app.predictive.registry")


class ModelRegistry:
    """
    Lightweight model registry tracking available forecasting models, executing
    deterministic candidate selection via leakage-safe backtesting, and recording selection provenance.
    Enforces the Principle of Parsimony: retains the simpler baseline model unless an advanced model
    demonstrates reliable, statistically meaningful improvement (>= 3.0% error reduction).
    """

    MODEL_TIERS: ClassVar[dict[str, int]] = {
        "naive": 0,
        "seasonal_naive": 0,
        "moving_average": 0,
        "exponential_smoothing": 1,
        "croston": 1,
        "holt_winters": 2,
        "ridge_lagged": 2,
        "arima": 2,
    }

    PARSIMONY_THRESHOLD: ClassVar[float] = 0.03  # 3.0% minimum relative improvement required

    DEFAULT_FACTORIES: ClassVar[dict[str, Callable[[], BaseForecaster]]] = {
        "naive": lambda: NaiveForecaster(),
        "seasonal_naive": lambda: SeasonalNaiveForecaster(),
        "moving_average": lambda: MovingAverageForecaster(),
        "exponential_smoothing": lambda: ExponentialSmoothingForecaster(),
        "croston": lambda: CrostonForecaster(),
        "holt_winters": lambda: HoltWintersForecaster(),
        "ridge_lagged": lambda: RidgeLaggedForecaster(),
        "arima": lambda: ARIMAForecaster(),
    }

    def __init__(self) -> None:
        self._history: list[dict[str, Any]] = []

    def get_candidate_factories(
        self,
        policy: ModelPolicy = ModelPolicy.VALIDATED_BEST,
        specific_model: str | None = None,
        is_intermittent: bool = False,
    ) -> dict[str, Callable[[], BaseForecaster]]:
        """Filter candidate models according to requested policy and series characteristics."""
        if policy == ModelPolicy.SPECIFIC_MODEL and specific_model:
            model_key = specific_model.lower().strip()
            if model_key in self.DEFAULT_FACTORIES:
                return {model_key: self.DEFAULT_FACTORIES[model_key]}
            raise ValueError(f"Requested model '{specific_model}' is not registered.")

        if policy == ModelPolicy.BASELINE_ONLY:
            return {
                k: v for k, v in self.DEFAULT_FACTORIES.items()
                if self.MODEL_TIERS.get(k, 0) <= 1
            }

        # Default: VALIDATED_BEST evaluates all candidate baselines and statistical models
        candidates = dict(self.DEFAULT_FACTORIES)
        # If series is intermittent, prioritize Croston over non-seasonal Holt-Winters
        if is_intermittent and "croston" in candidates:
            # Place Croston near the top of evaluation
            reordered = {"croston": candidates["croston"]}
            reordered.update(candidates)
            return reordered

        return candidates

    def get_candidates(
        self,
        policy: ModelPolicy = ModelPolicy.VALIDATED_BEST,
        specific_model: str | None = None,
    ) -> list[BaseForecaster]:
        """Instantiate candidate model instances for inspection or evaluation."""
        factories = self.get_candidate_factories(policy=policy, specific_model=specific_model)
        return [f() for f in factories.values()]

    def evaluate_and_select(
        self,
        series: Any,
        candidates: list[BaseForecaster] | None = None,
        policy: ModelPolicy = ModelPolicy.VALIDATED_BEST,
        horizon: int = 1,
        target_metric: str = "metric",
        frequency: str = "monthly",
        ranking_metric: str = "mae",
    ) -> tuple[BaseForecaster, EvaluationMetrics, ModelMetadata]:
        """Backtest and select the best validated model from candidate list or registry."""
        import copy
        y = series.values if hasattr(series, "values") else np.asarray(series, dtype=np.float64)
        if candidates is None:
            best_m, best_eval, meta, _ = self.select_best_model(
                y=y,
                target_metric=target_metric,
                frequency=frequency,
                policy=policy,
            )
            return best_m, best_eval, meta

        # Custom candidates list passed
        candidate_evals: dict[str, EvaluationMetrics] = {}
        candidate_models: dict[str, BaseForecaster] = {}

        for cand in candidates:
            cand_copy = copy.deepcopy(cand)
            factory = lambda c=cand: copy.deepcopy(c)
            try:
                bt_res = ExpandingWindowBacktester.evaluate(
                    forecaster_factory=factory,
                    y=y,
                    horizon=horizon,
                )
                candidate_evals[cand.name] = bt_res.metrics
                cand_copy.fit(y)
                candidate_models[cand.name] = cand_copy
            except Exception as exc:  # noqa: BLE001
                logger.debug(f"Candidate {cand.name} failed backtesting: {exc}")
                continue

        if not candidate_evals:
            fallback = NaiveForecaster().fit(y)
            default_metrics = EvaluationMetrics(mae=0.0, rmse=0.0, smape=0.0)
            meta = ModelMetadata(
                name="naive",
                version="1.0",
                model_type="baseline",
                parameters=fallback.parameters,
                selection_reason="Fallback: Custom candidates failed backtesting.",
                is_baseline=True,
            )
            return fallback, default_metrics, meta

        selected_model, selected_eval, meta = self._apply_parsimony_selection(
            candidate_evals=candidate_evals,
            candidate_models=candidate_models,
            ranking_metric="mae",
        )
        return selected_model, selected_eval, meta

    def _apply_parsimony_selection(
        self,
        candidate_evals: dict[str, EvaluationMetrics],
        candidate_models: dict[str, BaseForecaster],
        ranking_metric: str = "mae",
    ) -> tuple[BaseForecaster, EvaluationMetrics, ModelMetadata]:
        """
        Select best model applying the Principle of Parsimony:
        If an advanced model (Tier 1 or 2) does not outperform a simpler baseline (Tier 0 or 1)
        by at least PARSIMONY_THRESHOLD (3.0%), retain the simpler model.
        """
        # Find raw best model across all candidates
        raw_best_name = None
        raw_best_score = float("inf")

        for name, metrics in candidate_evals.items():
            score = getattr(metrics, ranking_metric, metrics.mae)
            if np.isfinite(score) and score < raw_best_score:
                raw_best_score = score
                raw_best_name = name

        if raw_best_name is None:
            raw_best_name = next(iter(candidate_models.keys()), "naive")
            raw_best_score = 0.0

        raw_tier = self.MODEL_TIERS.get(raw_best_name, 2)

        # If raw best is Tier 0 (naive/simple), no simpler baseline exists
        if raw_tier == 0:
            selected_name = raw_best_name
            selected_model = candidate_models[selected_name]
            selected_metrics = candidate_evals[selected_name]
            reason = (
                f"Selected baseline '{selected_name}' (Tier 0) through temporal backtesting across "
                f"{len(candidate_evals)} candidates; achieved lowest {ranking_metric.upper()} of {raw_best_score:.2f}."
            )
            metadata = ModelMetadata(
                name=selected_model.name,
                version=selected_model.version,
                model_type="baseline",
                parameters=selected_model.parameters,
                selection_reason=reason,
                is_baseline=True,
            )
            return selected_model, selected_metrics, metadata

        # Find best simpler baseline candidate (tier < raw_tier)
        simpler_candidates = {
            name: metrics
            for name, metrics in candidate_evals.items()
            if self.MODEL_TIERS.get(name, 2) < raw_tier
        }

        if simpler_candidates:
            best_simpler_name = None
            best_simpler_score = float("inf")
            for name, metrics in simpler_candidates.items():
                s = getattr(metrics, ranking_metric, metrics.mae)
                if np.isfinite(s) and s < best_simpler_score:
                    best_simpler_score = s
                    best_simpler_name = name

            if best_simpler_name is not None and np.isfinite(best_simpler_score):
                if best_simpler_score <= 1e-4:
                    # Simpler baseline is already virtually perfect; retain it
                    improvement = 0.0
                else:
                    improvement = (best_simpler_score - raw_best_score) / best_simpler_score
                    if not np.isfinite(improvement):
                        improvement = 0.0

                if improvement < self.PARSIMONY_THRESHOLD:
                    # Parsimony rule triggered: Advanced model did not improve by >= 3%
                    selected_name = best_simpler_name
                    selected_model = candidate_models[selected_name]
                    selected_metrics = candidate_evals[selected_name]
                    reason = (
                        f"Candidate '{raw_best_name}' (Tier {raw_tier}) achieved {ranking_metric.upper()} of {raw_best_score:.2f} "
                        f"but did not exceed the {self.PARSIMONY_THRESHOLD * 100:.1f}% improvement threshold over "
                        f"simpler baseline '{best_simpler_name}' (Tier {self.MODEL_TIERS.get(best_simpler_name, 0)}, "
                        f"{ranking_metric.upper()} {best_simpler_score:.2f}, improvement {improvement * 100:.1f}%). "
                        f"Retained parsimonious baseline '{best_simpler_name}'."
                    )
                else:
                    # Advanced model reliably outperformed baseline by >= 3%
                    selected_name = raw_best_name
                    selected_model = candidate_models[selected_name]
                    selected_metrics = candidate_evals[selected_name]
                    reason = (
                        f"Selected advanced model '{selected_name}' (Tier {raw_tier}) through temporal backtesting across "
                        f"{len(candidate_evals)} candidates; achieved lowest {ranking_metric.upper()} of {raw_best_score:.2f} "
                        f"(outperformed baseline '{best_simpler_name}' by {improvement * 100:.1f}%)."
                    )
                metadata = ModelMetadata(
                    name=selected_model.name,
                    version=selected_model.version,
                    model_type="baseline" if selected_model.is_baseline else "statistical",
                    parameters=selected_model.parameters,
                    selection_reason=reason,
                    is_baseline=selected_model.is_baseline,
                )
                return selected_model, selected_metrics, metadata

        # No simpler candidate was available in the evaluated pool
        selected_name = raw_best_name
        selected_model = candidate_models[selected_name]
        selected_metrics = candidate_evals[selected_name]
        reason = (
            f"Selected '{selected_name}' through temporal backtesting across {len(candidate_evals)} candidates; "
            f"achieved lowest {ranking_metric.upper()} of {raw_best_score:.2f}."
        )
        metadata = ModelMetadata(
            name=selected_model.name,
            version=selected_model.version,
            model_type="baseline" if selected_model.is_baseline else "statistical",
            parameters=selected_model.parameters,
            selection_reason=reason,
            is_baseline=selected_model.is_baseline,
        )
        return selected_model, selected_metrics, metadata

    def select_best_model(
        self,
        y: np.ndarray,
        target_metric: str,
        frequency: str,
        policy: ModelPolicy = ModelPolicy.VALIDATED_BEST,
        specific_model: str | None = None,
        ranking_metric: str = "mae",
    ) -> tuple[BaseForecaster, EvaluationMetrics, ModelMetadata, dict[str, EvaluationMetrics]]:
        """
        Backtest candidate models across historical cutoffs and select the optimal model
        strictly based on deterministic out-of-sample accuracy while enforcing parsimony.
        """
        arr = np.asarray(y, dtype=np.float64)
        zero_ratio = float(np.mean(np.abs(arr) < 1e-5)) if len(arr) > 0 else 0.0
        is_intermittent = zero_ratio >= 0.25 and not np.any(arr < -1e-6)

        factories = self.get_candidate_factories(
            policy=policy,
            specific_model=specific_model,
            is_intermittent=is_intermittent,
        )
        candidate_evals: dict[str, EvaluationMetrics] = {}
        candidate_models: dict[str, BaseForecaster] = {}

        for name, factory in factories.items():
            try:
                # 1. Backtest model out-of-sample with expanding window
                bt_result = ExpandingWindowBacktester.evaluate(
                    forecaster_factory=factory,
                    y=arr,
                    horizon=1,
                )
                candidate_evals[name] = bt_result.metrics

                # 2. Fit full-dataset instance for production forecast
                full_model = factory()
                full_model.fit(arr)
                candidate_models[name] = full_model
            except Exception as exc:  # noqa: BLE001
                # Model failed to converge, insufficient points, or rejected for series
                logger.debug(f"Candidate {name} failed evaluation on series: {exc}")
                continue

        if not candidate_evals:
            # Fallback to robust naive forecaster
            fallback_factory = self.DEFAULT_FACTORIES["naive"]
            full_model = fallback_factory()
            full_model.fit(arr)
            default_metrics = EvaluationMetrics(mae=0.0, rmse=0.0, smape=0.0)
            meta = ModelMetadata(
                name="naive",
                version="1.0",
                model_type="baseline",
                parameters=full_model.parameters,
                selection_reason="Fallback: All candidate models failed validation on series.",
                is_baseline=True,
            )
            return full_model, default_metrics, meta, {"naive": default_metrics}

        selected_model, selected_metrics, metadata = self._apply_parsimony_selection(
            candidate_evals=candidate_evals,
            candidate_models=candidate_models,
            ranking_metric=ranking_metric,
        )

        # Log into in-memory audit registry
        self._history.append({
            "target": target_metric,
            "frequency": frequency,
            "model_name": selected_model.name,
            "metrics": selected_metrics.model_dump(),
            "timestamp": datetime.now(UTC).isoformat(),
        })

        return selected_model, selected_metrics, metadata, candidate_evals
